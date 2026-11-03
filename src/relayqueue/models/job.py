import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from relayqueue.database.base import Base

if TYPE_CHECKING:
    from relayqueue.models.job_attempt import JobAttempt


class Job(Base):
    __tablename__ = "jobs"

    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending', 'running', 'completed', 'retrying', "
            "'failed', 'dead_letter', 'cancelled'"
            ")",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0",
            name="ck_jobs_attempt_limits",
        ),
        Index(
            "uq_jobs_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_jobs_status_available_priority",
            "status",
            "available_at",
            "priority",
        ),
        Index(
            "ix_jobs_status_lease_expiry",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    task_type: Mapped[str] = mapped_column(String(100), nullable=False)

    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workers.id", ondelete="SET NULL"),
        nullable=True,
    )

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    execution_attempts: Mapped[list["JobAttempt"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
