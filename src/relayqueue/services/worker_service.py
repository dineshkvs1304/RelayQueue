from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayqueue.models.job import Job
from relayqueue.models.job_attempt import JobAttempt
from relayqueue.models.worker import Worker

BASE_RETRY_DELAY_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 300
DEFAULT_LEASE_DURATION_SECONDS = 30


def claim_next_job(
    db: Session,
    worker_id: UUID,
    lease_duration_seconds: int = DEFAULT_LEASE_DURATION_SECONDS,
) -> tuple[Job, JobAttempt] | None:
    """Claim one available job and assign it to an active worker."""
    try:
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())

        if worker is None or worker.status != "active":
            raise ValueError("Worker does not exist or is not active")

        statement = (
            select(Job)
            .where(
                Job.status.in_(["pending", "retrying"]),
                Job.available_at <= func.now(),
                Job.attempts < Job.max_attempts,
            )
            .order_by(
                Job.priority.desc(),
                Job.created_at.asc(),
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )

        job = db.scalar(statement)

        if job is None:
            db.rollback()
            return None

        now = datetime.now(UTC)

        job.attempts += 1
        job.status = "running"
        job.locked_by = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_duration_seconds)

        attempt = JobAttempt(
            job_id=job.id,
            worker_id=worker_id,
            attempt_number=job.attempts,
            status="running",
        )

        db.add(attempt)
        db.commit()
        db.refresh(job)
        db.refresh(attempt)

        return job, attempt

    except Exception:
        db.rollback()
        raise


def _get_owned_running_job(
    db: Session,
    job_id: UUID,
    attempt_id: UUID,
) -> tuple[Job, JobAttempt]:
    """Load and validate a job and its current worker-owned attempt."""
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    attempt = db.scalar(select(JobAttempt).where(JobAttempt.id == attempt_id).with_for_update())

    if job is None or attempt is None:
        raise LookupError("Job or attempt not found")

    if job.status != "running" or attempt.status != "running":
        raise ValueError("Job or attempt is no longer running")

    if job.locked_by is None or job.locked_by != attempt.worker_id:
        raise ValueError("Worker does not own this job")

    if job.lease_expires_at is None:
        raise ValueError("Job has no active lease")

    now = datetime.now(UTC)

    if job.lease_expires_at <= now:
        raise ValueError("Job lease has expired")

    if attempt.job_id != job.id or attempt.attempt_number != job.attempts:
        raise ValueError("Attempt is not the current attempt for this job")

    return job, attempt


def complete_job(
    db: Session,
    job_id: UUID,
    attempt_id: UUID,
) -> None:
    try:
        job, attempt = _get_owned_running_job(db, job_id, attempt_id)

        now = datetime.now(UTC)

        job.status = "completed"
        job.updated_at = now
        job.locked_by = None
        job.lease_expires_at = None

        attempt.status = "completed"
        attempt.finished_at = now

        db.commit()

    except Exception:
        db.rollback()
        raise


def fail_job(
    db: Session,
    job_id: UUID,
    attempt_id: UUID,
    error_message: str,
) -> str:
    try:
        job, attempt = _get_owned_running_job(db, job_id, attempt_id)

        now = datetime.now(UTC)

        attempt.status = "failed"
        attempt.finished_at = now
        attempt.error_message = error_message[:4000]

        job.locked_by = None
        job.lease_expires_at = None

        if job.attempts < job.max_attempts:
            delay = min(
                BASE_RETRY_DELAY_SECONDS * (2 ** (job.attempts - 1)),
                MAX_RETRY_DELAY_SECONDS,
            )
            job.status = "retrying"
            job.available_at = now + timedelta(seconds=delay)
            outcome = "retrying"
        else:
            job.status = "dead_letter"
            outcome = "dead_letter"

        job.updated_at = now

        db.commit()
        return outcome

    except Exception:
        db.rollback()
        raise


def renew_job_lease(
    db: Session,
    job_id: UUID,
    attempt_id: UUID,
    worker_id: UUID,
    lease_duration_seconds: int = DEFAULT_LEASE_DURATION_SECONDS,
) -> datetime:
    """Extend the lease for a job currently owned by this worker."""
    try:
        job, attempt = _get_owned_running_job(db, job_id, attempt_id)

        if job.locked_by != worker_id or attempt.worker_id != worker_id:
            raise ValueError("Worker does not own this job")

        now = datetime.now(UTC)
        job.lease_expires_at = now + timedelta(seconds=lease_duration_seconds)
        job.updated_at = now

        db.commit()
        return job.lease_expires_at

    except Exception:
        db.rollback()
        raise


def recover_expired_jobs(
    db: Session,
    batch_size: int = 100,
) -> int:
    """
    Recover jobs whose worker leases have expired.

    Returns the number of jobs recovered.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    recovered_count = 0

    try:
        now = datetime.now(UTC)

        expired_jobs = db.scalars(
            select(Job)
            .where(
                Job.status == "running",
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at <= now,
            )
            .order_by(Job.lease_expires_at.asc())
            .with_for_update(skip_locked=True)
            .limit(batch_size)
        ).all()

        for job in expired_jobs:
            attempt = db.scalar(
                select(JobAttempt)
                .where(
                    JobAttempt.job_id == job.id,
                    JobAttempt.attempt_number == job.attempts,
                    JobAttempt.status == "running",
                )
                .with_for_update()
            )

            if attempt is not None:
                attempt.status = "failed"
                attempt.finished_at = now
                attempt.error_message = "Worker lease expired"

            job.locked_by = None
            job.lease_expires_at = None
            job.updated_at = now

            if job.attempts < job.max_attempts:
                delay = min(
                    BASE_RETRY_DELAY_SECONDS * (2 ** (job.attempts - 1)),
                    MAX_RETRY_DELAY_SECONDS,
                )
                job.status = "retrying"
                job.available_at = now + timedelta(seconds=delay)
            else:
                job.status = "dead_letter"

            recovered_count += 1

        db.commit()
        return recovered_count

    except Exception:
        db.rollback()
        raise
