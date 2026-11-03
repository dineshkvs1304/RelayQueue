from uuid import uuid4

from sqlalchemy import update

from relayqueue.models.worker import Worker

VALID_WORKER = {
    "name": "test-worker",
    "hostname": "localhost",
}


def test_register_worker(client):
    response = client.post("/workers", json=VALID_WORKER)

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "test-worker"
    assert data["hostname"] == "localhost"
    assert data["status"] == "active"
    assert data["id"] is not None
    assert data["last_heartbeat"] is not None
    assert data["started_at"] is not None


def test_register_multiple_workers(client):
    first = client.post("/workers", json=VALID_WORKER)

    second = client.post(
        "/workers",
        json={
            "name": "test-worker-2",
            "hostname": "localhost-2",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201

    assert first.json()["id"] != second.json()["id"]


def test_register_worker_with_missing_name(client):
    response = client.post(
        "/workers",
        json={"hostname": "localhost"},
    )

    assert response.status_code == 422


def test_register_worker_with_missing_hostname(client):
    response = client.post(
        "/workers",
        json={"name": "test-worker"},
    )

    assert response.status_code == 422


def test_worker_heartbeat(client):
    registration = client.post(
        "/workers",
        json=VALID_WORKER,
    )

    worker_id = registration.json()["id"]
    original_heartbeat = registration.json()["last_heartbeat"]

    response = client.post(f"/workers/{worker_id}/heartbeat")

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == worker_id
    assert data["status"] == "active"
    assert data["last_heartbeat"] is not None
    assert data["last_heartbeat"] >= original_heartbeat


def test_heartbeat_for_nonexistent_worker(client):
    worker_id = str(uuid4())

    response = client.post(f"/workers/{worker_id}/heartbeat")

    assert response.status_code == 404
    assert response.json()["detail"] == "Worker not found"


def test_heartbeat_with_invalid_uuid(client):
    response = client.post("/workers/not-a-valid-uuid/heartbeat")

    assert response.status_code == 422


def test_heartbeat_reactivates_offline_worker(client, db_session):
    registration = client.post(
        "/workers",
        json=VALID_WORKER,
    )

    worker_id = registration.json()["id"]

    db_session.execute(update(Worker).where(Worker.id == worker_id).values(status="offline"))

    db_session.commit()
    db_session.expire_all()

    response = client.post(f"/workers/{worker_id}/heartbeat")

    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_draining_worker_can_heartbeat_without_becoming_active(
    client,
    db_session,
):
    registration = client.post("/workers", json=VALID_WORKER)
    worker_id = registration.json()["id"]

    db_session.execute(update(Worker).where(Worker.id == worker_id).values(status="draining"))
    db_session.commit()
    db_session.expire_all()

    response = client.post(f"/workers/{worker_id}/heartbeat")

    assert response.status_code == 200
    assert response.json()["status"] == "draining"
    assert response.json()["last_heartbeat"] is not None
