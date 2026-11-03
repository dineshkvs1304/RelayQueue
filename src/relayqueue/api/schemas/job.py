from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobCreate(BaseModel):
    task_type: str = Field(min_length=1, max_length=100)

    payload: dict[str, Any] = Field(default_factory=dict)

    priority: int = Field(default=0, ge=0, le=100)

    max_attempts: int = Field(default=3, ge=1, le=10)

    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at(cls, value):
        if value is None:
            return value

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone, such as Z or +05:30")

        if value <= datetime.now(UTC):
            raise ValueError("scheduled_at must be in the future")

        return value


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_type: str
    payload: dict[str, Any]
    idempotency_key: str | None = None
    status: str
    priority: int
    attempts: int
    max_attempts: int
    available_at: datetime
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int


class JobAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    worker_id: UUID | None
    attempt_number: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None
    result: dict[str, Any] | None


class DeadLetterListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
