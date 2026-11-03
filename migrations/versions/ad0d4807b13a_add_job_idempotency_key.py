
"""add job idempotency key

Revision ID: ad0d4807b13a
Revises: 97653e2723d9
Create Date: 2026-11-03 15:22:21.479321
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ad0d4807b13a"
down_revision: Union[str, Sequence[str], None] = "97653e2723d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {
        column["name"] for column in inspector.get_columns("jobs")
    }

    if "idempotency_key" not in columns:
        op.add_column(
            "jobs",
            sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        )

    inspector = sa.inspect(bind)
    indexes = {
        index["name"] for index in inspector.get_indexes("jobs")
    }

    if "uq_jobs_idempotency_key" not in indexes:
        op.create_index(
            "uq_jobs_idempotency_key",
            "jobs",
            ["idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = {
        index["name"] for index in inspector.get_indexes("jobs")
    }

    if "uq_jobs_idempotency_key" in indexes:
        op.drop_index("uq_jobs_idempotency_key", table_name="jobs")

    inspector = sa.inspect(bind)
    columns = {
        column["name"] for column in inspector.get_columns("jobs")
    }

    if "idempotency_key" in columns:
        op.drop_column("jobs", "idempotency_key")
