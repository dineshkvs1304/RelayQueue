from uuid import UUID, uuid4

from relayqueue.services.worker_registry_service import (
    update_worker_status,
)


def test_worker_can_be_marked_draining(client, db_session):
    response = client.post(
        "/workers",
        json={"name": "status-worker", "hostname": "localhost"},
    )
    worker_id = UUID(response.json()["id"])

    worker = update_worker_status(
        db_session,
        worker_id,
        "draining",
    )

    assert worker is not None
    assert worker.status == "draining"


def test_worker_can_be_marked_offline(client, db_session):
    response = client.post(
        "/workers",
        json={"name": "status-worker", "hostname": "localhost"},
    )
    worker_id = UUID(response.json()["id"])

    worker = update_worker_status(
        db_session,
        worker_id,
        "offline",
    )

    assert worker is not None
    assert worker.status == "offline"


def test_heartbeat_reactivates_offline_worker(client, db_session):
    from relayqueue.services.worker_registry_service import record_heartbeat

    response = client.post(
        "/workers",
        json={"name": "status-worker", "hostname": "localhost"},
    )
    worker_id = UUID(response.json()["id"])

    update_worker_status(db_session, worker_id, "offline")

    worker = record_heartbeat(db_session, worker_id)

    assert worker is not None
    assert worker.status == "active"


def test_status_update_for_missing_worker_returns_none(db_session):
    worker = update_worker_status(
        db_session,
        uuid4(),
        "offline",
    )

    assert worker is None
