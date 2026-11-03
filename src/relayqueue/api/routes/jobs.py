from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy.orm import Session

from relayqueue.api.dependencies import get_db
from relayqueue.api.schemas.job import (
    DeadLetterListResponse,
    JobAttemptResponse,
    JobCreate,
    JobListResponse,
    JobResponse,
)
from relayqueue.services import job_service

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------
# 1. Submit a new job
# ---------------------------------------------------------


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_job(
    job_data: JobCreate,
    response: Response,
    db: DatabaseSession,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
        ),
    ] = None,
):
    try:
        job, created = job_service.create_job(
            db,
            job_data.model_dump(),
            idempotency_key=idempotency_key,
        )

        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK

        return job

    except job_service.IdempotencyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )


# ---------------------------------------------------------
# 2. List all jobs with pagination and optional status
# ---------------------------------------------------------


@router.get(
    "",
    response_model=JobListResponse,
)
def retrieve_jobs(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    job_status: Literal[
        "pending",
        "running",
        "completed",
        "retrying",
        "failed",
        "dead_letter",
        "cancelled",
    ]
    | None = Query(default=None, alias="status"),
):
    jobs, total = job_service.list_jobs(
        db,
        page=page,
        page_size=page_size,
        status=job_status,
    )

    return JobListResponse(
        items=jobs,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------
# 3. List dead-letter jobs
# IMPORTANT: Keep this before /{job_id}
# ---------------------------------------------------------


@router.get(
    "/dead-letter",
    response_model=DeadLetterListResponse,
)
def retrieve_dead_letter_jobs(
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    jobs, total = job_service.list_dead_letter_jobs(
        db,
        page=page,
        page_size=page_size,
    )

    return DeadLetterListResponse(
        items=jobs,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------
# 4. Retrieve execution attempts for a job
# IMPORTANT: Keep this before /{job_id}
# ---------------------------------------------------------


@router.get(
    "/{job_id}/attempts",
    response_model=list[JobAttemptResponse],
)
def retrieve_job_attempts(
    job_id: UUID,
    db: DatabaseSession,
):
    attempts = job_service.get_job_attempts(
        db,
        job_id,
    )

    if attempts is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return attempts


# ---------------------------------------------------------
# 5. Manually retry a dead-letter job
# IMPORTANT: Keep this before /{job_id}
# ---------------------------------------------------------


@router.post(
    "/{job_id}/retry",
    response_model=JobResponse,
)
def retry_dead_letter_job(
    job_id: UUID,
    db: DatabaseSession,
):
    try:
        return job_service.retry_dead_letter_job(
            db,
            job_id,
        )

    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )


# ---------------------------------------------------------
# 6. Retrieve one job by ID
# ---------------------------------------------------------


@router.get(
    "/{job_id}",
    response_model=JobResponse,
)
def retrieve_job(
    job_id: UUID,
    db: DatabaseSession,
):
    job = job_service.get_job(
        db,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return job


# ---------------------------------------------------------
# 7. Cancel a pending job
# ---------------------------------------------------------


@router.delete(
    "/{job_id}",
    response_model=JobResponse,
)
def delete_pending_job(
    job_id: UUID,
    db: DatabaseSession,
):
    try:
        return job_service.cancel_job(
            db,
            job_id,
        )

    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )
