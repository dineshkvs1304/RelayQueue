from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import update

from relayqueue.models.job import Job
from relayqueue.models.job_attempt import JobAttempt
from relayqueue.models.worker import Worker
from relayqueue.services.worker_service import (
    claim_next_job,
    complete_job,
    fail_job,
    recover_expired_jobs,
    renew_job_lease,
)

VALID_JOB = {
    "task_type": "send_email",
    "payload": {"recipient": "test@example.com"},
    "priority": 10,
    "max_attempts": 3,
}

VALID_WORKER = {
    "name": "lifecycle-worker",
    "hostname": "localhost",
}


def create_worker(client):
    response = client.post("/workers", json=VALID_WORKER)
    assert response.status_code == 201
    return UUID(response.json()["id"])


def create_job(client, max_attempts=3, priority=10):
    data = {
        **VALID_JOB,
        "max_attempts": max_attempts,
        "priority": priority,
    }
    response = client.post("/jobs", json=data)
    assert response.status_code == 201
    return UUID(response.json()["id"])


def test_worker_claims_pending_job(client, db_session):
    worker_id = create_worker(client)
    job_id = create_job(client)

    result = claim_next_job(db_session, worker_id)

    assert result is not None
    job, attempt = result

    assert job.id == job_id
    assert job.status == "running"
    assert job.locked_by == worker_id
    assert job.attempts == 1
    assert job.lease_expires_at is not None

    assert attempt.job_id == job_id
    assert attempt.worker_id == worker_id
    assert attempt.attempt_number == 1
    assert attempt.status == "running"


def test_worker_cannot_claim_same_job_twice(client, db_session):
    first_worker = create_worker(client)
    second_worker = create_worker(client)
    create_job(client)

    first_result = claim_next_job(db_session, first_worker)
    second_result = claim_next_job(db_session, second_worker)

    assert first_result is not None
    assert second_result is None


def test_claim_returns_none_when_no_jobs_exist(client, db_session):
    worker_id = create_worker(client)

    result = claim_next_job(db_session, worker_id)

    assert result is None


def test_inactive_worker_cannot_claim_job(client, db_session):
    worker_id = create_worker(client)
    create_job(client)

    db_session.execute(update(Worker).where(Worker.id == worker_id).values(status="offline"))
    db_session.commit()
    db_session.expire_all()

    with pytest.raises(ValueError, match="not active"):
        claim_next_job(db_session, worker_id)


def test_complete_job_successfully(client, db_session):
    worker_id = create_worker(client)
    job_id = create_job(client)

    job, attempt = claim_next_job(db_session, worker_id)

    complete_job(db_session, job.id, attempt.id)

    db_session.expire_all()
    saved_job = db_session.get(Job, job_id)
    saved_attempt = db_session.get(JobAttempt, attempt.id)

    assert saved_job.status == "completed"
    assert saved_job.locked_by is None
    assert saved_job.lease_expires_at is None
    assert saved_attempt.status == "completed"
    assert saved_attempt.finished_at is not None


def test_failed_job_enters_retrying_state(client, db_session):
    worker_id = create_worker(client)
    job_id = create_job(client, max_attempts=3)

    job, attempt = claim_next_job(db_session, worker_id)

    outcome = fail_job(
        db_session,
        job.id,
        attempt.id,
        "Temporary service failure",
    )

    db_session.expire_all()
    saved_job = db_session.get(Job, job_id)
    saved_attempt = db_session.get(JobAttempt, attempt.id)

    assert outcome == "retrying"
    assert saved_job.status == "retrying"
    assert saved_job.attempts == 1
    assert saved_job.available_at > datetime.now(UTC)
    assert saved_job.locked_by is None
    assert saved_job.lease_expires_at is None
    assert saved_attempt.status == "failed"
    assert saved_attempt.error_message == "Temporary service failure"


def test_failed_job_moves_to_dead_letter_after_max_attempts(
    client,
    db_session,
):
    worker_id = create_worker(client)
    job_id = create_job(client, max_attempts=1)

    job, attempt = claim_next_job(db_session, worker_id)

    outcome = fail_job(
        db_session,
        job.id,
        attempt.id,
        "Permanent failure",
    )

    db_session.expire_all()
    saved_job = db_session.get(Job, job_id)

    assert outcome == "dead_letter"
    assert saved_job.status == "dead_letter"
    assert saved_job.attempts == 1
    assert saved_job.locked_by is None
    assert saved_job.lease_expires_at is None


def test_wrong_worker_cannot_renew_lease(client, db_session):
    first_worker = create_worker(client)
    second_worker = create_worker(client)
    create_job(client)  # Added: create a job to claim

    job, attempt = claim_next_job(db_session, first_worker)

    with pytest.raises(ValueError, match="does not own"):
        renew_job_lease(
            db_session,
            job.id,
            attempt.id,
            second_worker,
        )


def test_lease_can_be_renewed_by_owner(client, db_session):
    worker_id = create_worker(client)
    create_job(client)  # Added: create a job to claim

    job, attempt = claim_next_job(
        db_session,
        worker_id,
        lease_duration_seconds=30,
    )

    old_expiry = job.lease_expires_at

    new_expiry = renew_job_lease(
        db_session,
        job.id,
        attempt.id,
        worker_id,
        lease_duration_seconds=60,
    )

    assert new_expiry > old_expiry


def test_expired_lease_rejects_job_completion(client, db_session):
    worker_id = create_worker(client)
    create_job(client)  # Added: create a job to claim

    job, attempt = claim_next_job(
        db_session,
        worker_id,
    )

    expired_time = datetime.now(UTC) - timedelta(seconds=10)

    db_session.execute(update(Job).where(Job.id == job.id).values(lease_expires_at=expired_time))
    db_session.commit()
    db_session.expire_all()

    with pytest.raises(ValueError, match="lease has expired"):
        complete_job(db_session, job.id, attempt.id)


def test_expired_job_is_recovered(client, db_session):
    worker_id = create_worker(client)
    job_id = create_job(client, max_attempts=3)

    job, attempt = claim_next_job(db_session, worker_id)

    expired_time = datetime.now(UTC) - timedelta(seconds=10)

    db_session.execute(update(Job).where(Job.id == job_id).values(lease_expires_at=expired_time))
    db_session.commit()
    db_session.expire_all()

    recovered = recover_expired_jobs(db_session)

    db_session.expire_all()
    saved_job = db_session.get(Job, job_id)
    saved_attempt = db_session.get(JobAttempt, attempt.id)

    assert recovered == 1
    assert saved_job.status == "retrying"
    assert saved_job.locked_by is None
    assert saved_job.lease_expires_at is None
    assert saved_attempt.status == "failed"
    assert saved_attempt.error_message == "Worker lease expired"


def test_expired_job_goes_to_dead_letter_on_final_attempt(
    client,
    db_session,
):
    worker_id = create_worker(client)
    job_id = create_job(client, max_attempts=1)

    job, attempt = claim_next_job(db_session, worker_id)

    expired_time = datetime.now(UTC) - timedelta(seconds=10)

    db_session.execute(update(Job).where(Job.id == job_id).values(lease_expires_at=expired_time))
    db_session.commit()
    db_session.expire_all()

    recovered = recover_expired_jobs(db_session)

    db_session.expire_all()
    saved_job = db_session.get(Job, job_id)

    assert recovered == 1
    assert saved_job.status == "dead_letter"
    assert saved_job.attempts == 1


def test_crashed_worker_job_is_recovered_and_completed_by_another_worker(
    client,
    db_session,
):
    # Register two independent workers.
    worker_a = create_worker(client)
    worker_b = create_worker(client)

    job_id = create_job(client, max_attempts=3)

    # Worker A claims the job.
    first_job, first_attempt = claim_next_job(
        db_session,
        worker_a,
        lease_duration_seconds=30,
    )

    assert first_job.id == job_id
    assert first_job.status == "running"
    assert first_attempt.worker_id == worker_a

    # Simulate Worker A crashing by expiring its lease.
    expired_time = datetime.now(UTC) - timedelta(seconds=10)

    db_session.execute(update(Job).where(Job.id == job_id).values(lease_expires_at=expired_time))
    db_session.commit()
    db_session.expire_all()

    # Recovery detects the expired lease.
    recovered = recover_expired_jobs(db_session)

    assert recovered == 1

    db_session.expire_all()

    recovered_job = db_session.get(Job, job_id)
    failed_attempt = db_session.get(JobAttempt, first_attempt.id)

    assert recovered_job.status == "retrying"
    assert recovered_job.locked_by is None
    assert recovered_job.lease_expires_at is None
    assert failed_attempt.status == "failed"
    assert failed_attempt.error_message == "Worker lease expired"

    # Make the retry immediately available instead of waiting 5 seconds.
    db_session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.commit()
    db_session.expire_all()

    # Worker B claims the recovered job.
    second_job, second_attempt = claim_next_job(
        db_session,
        worker_b,
    )

    assert second_job.id == job_id
    assert second_job.status == "running"
    assert second_job.locked_by == worker_b
    assert second_job.attempts == 2
    assert second_attempt.worker_id == worker_b
    assert second_attempt.attempt_number == 2

    # Worker B successfully completes the job.
    complete_job(
        db_session,
        second_job.id,
        second_attempt.id,
    )

    db_session.expire_all()

    final_job = db_session.get(Job, job_id)
    first_attempt_saved = db_session.get(
        JobAttempt,
        first_attempt.id,
    )
    second_attempt_saved = db_session.get(
        JobAttempt,
        second_attempt.id,
    )

    assert final_job.status == "completed"
    assert final_job.attempts == 2
    assert final_job.locked_by is None
    assert final_job.lease_expires_at is None

    assert first_attempt_saved.status == "failed"
    assert second_attempt_saved.status == "completed"
