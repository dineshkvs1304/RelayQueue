from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from relayqueue.api.dependencies import get_db
from relayqueue.api.schemas.worker import (
    WorkerRegister,
    WorkerResponse,
)
from relayqueue.services import worker_registry_service

router = APIRouter(
    prefix="/workers",
    tags=["Workers"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=WorkerResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_worker(
    worker_data: WorkerRegister,
    db: DatabaseSession,
):
    return worker_registry_service.register_worker(
        db,
        name=worker_data.name,
        hostname=worker_data.hostname,
    )


@router.post(
    "/{worker_id}/heartbeat",
    response_model=WorkerResponse,
)
def worker_heartbeat(
    worker_id: UUID,
    db: DatabaseSession,
):
    try:
        worker = worker_registry_service.record_heartbeat(
            db,
            worker_id,
        )

        if worker is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Worker not found",
            )

        return worker

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )
