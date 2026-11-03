from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayqueue.models.worker import Worker

WorkerStatus = Literal["active", "offline", "draining"]


def register_worker(
    db: Session,
    name: str,
    hostname: str,
) -> Worker:
    """Register a new worker and initialize its heartbeat."""
    try:
        now = datetime.now(UTC)

        worker = Worker(
            name=name,
            hostname=hostname,
            status="active",
            last_heartbeat=now,
        )

        db.add(worker)
        db.commit()
        db.refresh(worker)

        return worker

    except Exception:
        db.rollback()
        raise


def record_heartbeat(
    db: Session,
    worker_id: UUID,
) -> Worker | None:
    """
    Update a worker's heartbeat.

    Draining workers remain draining. Offline workers become active
    when they successfully reconnect.
    """
    try:
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())

        if worker is None:
            return None

        worker.last_heartbeat = datetime.now(UTC)

        if worker.status == "offline":
            worker.status = "active"

        db.commit()
        db.refresh(worker)

        return worker

    except Exception:
        db.rollback()
        raise


def update_worker_status(
    db: Session,
    worker_id: UUID,
    status: WorkerStatus,
) -> Worker | None:
    """Update a registered worker's operational status."""
    if status not in ("active", "offline", "draining"):
        raise ValueError("Invalid worker status")

    try:
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())

        if worker is None:
            return None

        worker.status = status

        db.commit()
        db.refresh(worker)

        return worker

    except Exception:
        db.rollback()
        raise
