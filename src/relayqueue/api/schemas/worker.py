from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkerRegister(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    hostname: str = Field(min_length=1, max_length=255)


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    hostname: str
    status: str
    last_heartbeat: datetime | None
    started_at: datetime
