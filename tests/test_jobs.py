from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import update

from relayqueue.models.job import Job

VALID_JOB = {
    "task_type": "send_email",
    "payload": {
        "recipient": "test@example.com",
        "subject": "Automated test",
    },
    "priority": 10,
    "max_attempts": 3,
}


def test_create_job(client):
    response = client.post("/jobs", json=VALID_JOB)

    assert response.status_code == 201

    data = response.json()

    assert data["task_type"] == "send_email"
    assert data["status"] == "pending"
    assert data["priority"] == 10
    assert data["attempts"] == 0
    assert data["max_attempts"] == 3
    assert data["payload"] == VALID_JOB["payload"]
    assert "id" in data


def test_get_existing_job(client):
    create_response = client.post("/jobs", json=VALID_JOB)
    job_id = create_response.json()["id"]

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id
    assert response.json()["status"] == "pending"


def test_get_nonexistent_job(client):
    job_id = str(uuid4())

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_get_job_with_invalid_uuid(client):
    response = client.get("/jobs/not-a-valid-uuid")

    assert response.status_code == 422


def test_list_jobs(client):
    client.post("/jobs", json=VALID_JOB)
    client.post("/jobs", json=VALID_JOB)

    response = client.get("/jobs")

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 20


def test_list_jobs_with_pagination(client):
    for _ in range(3):
        client.post("/jobs", json=VALID_JOB)

    response = client.get("/jobs?page=1&page_size=2")

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


def test_list_jobs_with_status_filter(client):
    client.post("/jobs", json=VALID_JOB)

    response = client.get("/jobs?status=pending")

    assert response.status_code == 200
    assert response.json()["total"] == 1

    response = client.get("/jobs?status=completed")

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_create_job_with_empty_task_type(client):
    payload = {
        **VALID_JOB,
        "task_type": "",
    }

    response = client.post("/jobs", json=payload)

    assert response.status_code == 422


def test_create_job_with_invalid_priority(client):
    payload = {
        **VALID_JOB,
        "priority": 101,
    }

    response = client.post("/jobs", json=payload)

    assert response.status_code == 422


def test_create_job_with_negative_priority(client):
    payload = {
        **VALID_JOB,
        "priority": -1,
    }

    response = client.post("/jobs", json=payload)

    assert response.status_code == 422


def test_create_job_with_invalid_max_attempts(client):
    payload = {
        **VALID_JOB,
        "max_attempts": 0,
    }

    response = client.post("/jobs", json=payload)

    assert response.status_code == 422


def test_create_job_with_max_attempts_above_limit(client):
    payload = {
        **VALID_JOB,
        "max_attempts": 11,
    }

    response = client.post("/jobs", json=payload)

    assert response.status_code == 422


def test_cancel_pending_job(client):
    create_response = client.post("/jobs", json=VALID_JOB)
    job_id = create_response.json()["id"]

    response = client.delete(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_nonexistent_job(client):
    job_id = str(uuid4())

    response = client.delete(f"/jobs/{job_id}")

    assert response.status_code == 404


def test_cannot_cancel_completed_job(client, db_session):
    create_response = client.post("/jobs", json=VALID_JOB)

    assert create_response.status_code == 201

    job_id = create_response.json()["id"]

    # Explicitly update the job in the test database.
    db_session.execute(update(Job).where(Job.id == job_id).values(status="completed"))

    # Commit the savepoint and clear cached ORM state.
    db_session.commit()
    db_session.expire_all()

    # Confirm the updated status before testing cancellation.
    job = db_session.get(Job, job_id)
    assert job.status == "completed"

    response = client.delete(f"/jobs/{job_id}")

    assert response.status_code == 409
    assert "completed" in response.json()["detail"]


def test_unsupported_task_type_is_accepted_at_submission(client):
    payload = {
        **VALID_JOB,
        "task_type": "unsupported_task",
    }

    response = client.post("/jobs", json=payload)

    assert response.status_code == 201
    assert response.json()["task_type"] == "unsupported_task"


def test_create_job_with_idempotency_key(client):
    headers = {"Idempotency-Key": "test-idempotency-001"}

    response = client.post(
        "/jobs",
        json=VALID_JOB,
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["idempotency_key"] == headers["Idempotency-Key"]


def test_duplicate_request_returns_existing_job(client):
    headers = {"Idempotency-Key": "test-idempotency-002"}

    first_response = client.post(
        "/jobs",
        json=VALID_JOB,
        headers=headers,
    )

    second_response = client.post(
        "/jobs",
        json=VALID_JOB,
        headers=headers,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert first_response.json()["id"] == second_response.json()["id"]


def test_idempotency_key_with_different_payload_returns_conflict(client):
    headers = {"Idempotency-Key": "test-idempotency-003"}

    first_response = client.post(
        "/jobs",
        json=VALID_JOB,
        headers=headers,
    )

    different_payload = {
        **VALID_JOB,
        "payload": {
            "recipient": "different@example.com",
            "subject": "Different request",
        },
    }

    second_response = client.post(
        "/jobs",
        json=different_payload,
        headers=headers,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_different_idempotency_keys_create_different_jobs(client):
    first_response = client.post(
        "/jobs",
        json=VALID_JOB,
        headers={"Idempotency-Key": "test-idempotency-004"},
    )

    second_response = client.post(
        "/jobs",
        json=VALID_JOB,
        headers={"Idempotency-Key": "test-idempotency-005"},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_response.json()["id"] != second_response.json()["id"]


def test_scheduled_job_cannot_be_reused_as_immediate_job(client):
    headers = {"Idempotency-Key": "scheduled-vs-immediate-001"}

    scheduled_payload = {
        **VALID_JOB,
        "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
    }

    first = client.post(
        "/jobs",
        json=scheduled_payload,
        headers=headers,
    )

    second = client.post(
        "/jobs",
        json=VALID_JOB,
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_immediate_job_cannot_be_reused_as_scheduled_job(client):
    headers = {"Idempotency-Key": "immediate-vs-scheduled-001"}

    first = client.post(
        "/jobs",
        json=VALID_JOB,
        headers=headers,
    )

    scheduled_payload = {
        **VALID_JOB,
        "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
    }

    second = client.post(
        "/jobs",
        json=scheduled_payload,
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
