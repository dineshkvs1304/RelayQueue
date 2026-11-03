from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from relayqueue.models.job import Job
from relayqueue.models.job_attempt import JobAttempt


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused for a different request."""


def _matches_request(job: Job, job_data: dict) -> bool:
    requested_schedule = job_data.get("scheduled_at")

    existing_available_at = job.available_at
    existing_created_at = job.created_at

    if existing_available_at.tzinfo is None:
        existing_available_at = existing_available_at.replace(tzinfo=UTC)

    if existing_created_at.tzinfo is None:
        existing_created_at = existing_created_at.replace(tzinfo=UTC)

    if requested_schedule is None:
        # An immediate job uses the database creation timestamp.
        schedule_matches = existing_available_at.astimezone(UTC) == existing_created_at.astimezone(
            UTC
        )
    else:
        schedule_matches = existing_available_at.astimezone(UTC) == requested_schedule.astimezone(
            UTC
        )

    return (
        job.task_type == job_data["task_type"]
        and job.payload == job_data["payload"]
        and job.priority == job_data["priority"]
        and job.max_attempts == job_data["max_attempts"]
        and schedule_matches
    )


def _get_existing_idempotent_job(
    db: Session,
    idempotency_key: str,
    job_data: dict,
) -> Job:
    existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))

    if existing is None:
        raise RuntimeError("Idempotency key conflict occurred but the existing job was not found")

    if not _matches_request(existing, job_data):
        raise IdempotencyConflictError(
            "Idempotency key has already been used with a different request"
        )

    return existing


def create_job(
    db: Session,
    job_data: dict,
    idempotency_key: str | None = None,
) -> tuple[Job, bool]:

    scheduled_at = job_data.get("scheduled_at")

    data = {
        "task_type": job_data["task_type"],
        "payload": job_data.get("payload", {}),
        "priority": job_data.get("priority", 0),
        "max_attempts": job_data.get("max_attempts", 3),
        "scheduled_at": scheduled_at,
    }

    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))

        if existing is not None:
            if not _matches_request(existing, data):
                raise IdempotencyConflictError(
                    "Idempotency key has already been used with a different request"
                )

            return existing, False

    job_data_for_model = {
        "task_type": data["task_type"],
        "payload": data["payload"],
        "priority": data["priority"],
        "max_attempts": data["max_attempts"],
    }

    if scheduled_at is not None:
        job_data_for_model["available_at"] = scheduled_at

    job = Job(
        **job_data_for_model,
        idempotency_key=idempotency_key,
    )

    db.add(job)

    try:
        db.commit()
        db.refresh(job)
        return job, True

    except IntegrityError:
        db.rollback()

        if idempotency_key is None:
            raise

        existing = _get_existing_idempotent_job(
            db,
            idempotency_key,
            data,
        )

        return existing, False


def get_job(db: Session, job_id: UUID) -> Job | None:
    return db.get(Job, job_id)


def list_jobs(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> tuple[list[Job], int]:

    query = select(Job)

    if status is not None:
        query = query.where(Job.status == status)

    total_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(total_query) or 0

    jobs_query = (
        query.order_by(
            Job.priority.desc(),
            Job.created_at.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    jobs = list(db.scalars(jobs_query).all())

    return jobs, total


def cancel_job(db: Session, job_id: UUID) -> Job:
    statement = (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == "pending",
        )
        .values(
            status="cancelled",
            updated_at=func.now(),
        )
    )

    result = db.execute(statement)

    if result.rowcount != 1:
        db.rollback()

        existing_job = db.get(Job, job_id)

        if existing_job is None:
            raise LookupError("Job not found")

        raise ValueError(f"Cannot cancel a job with status '{existing_job.status}'")

    db.commit()

    return db.get(Job, job_id)


def claim_next_job(db: Session) -> Job | None:
    statement = (
        select(Job)
        .where(
            Job.status == "pending",
            Job.available_at <= func.now(),
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

    job.status = "running"
    job.attempts += 1
    job.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(job)

    return job


def list_dead_letter_jobs(
    db: Session,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Job], int]:
    return list_jobs(
        db,
        page=page,
        page_size=page_size,
        status="dead_letter",
    )


def get_job_attempts(
    db: Session,
    job_id: UUID,
) -> list[JobAttempt] | None:
    job = db.get(Job, job_id)

    if job is None:
        return None

    statement = (
        select(JobAttempt)
        .where(JobAttempt.job_id == job_id)
        .order_by(JobAttempt.attempt_number.asc())
    )

    return list(db.scalars(statement).all())


def retry_dead_letter_job(
    db: Session,
    job_id: UUID,
) -> Job:
    try:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())

        if job is None:
            raise LookupError("Job not found")

        if job.status != "dead_letter":
            raise ValueError(
                f"Cannot requeue a job with status '{job.status}'. "
                "Only dead-letter jobs can be requeued."
            )

        now = datetime.now(UTC)

        # Grant another retry cycle without resetting attempt numbers.
        job.max_attempts += job.max_attempts

        job.status = "pending"
        job.available_at = now
        job.updated_at = now
        job.locked_by = None
        job.lease_expires_at = None

        db.commit()
        db.refresh(job)

        return job

    except Exception:
        db.rollback()
        raise
