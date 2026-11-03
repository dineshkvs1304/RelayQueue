
"""add job lease ownership

Revision ID: 97653e2723d9
Revises: 4b28d830ccbc
Create Date: 2026-11-02 21:28:17.133641

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "97653e2723d9"
down_revision: Union[str, Sequence[str], None] = "4b28d830ccbc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "jobs",
        sa.Column("locked_by", sa.Uuid(), nullable=True),
    )

    op.add_column(
        "jobs",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_jobs_status_lease_expiry",
        "jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_jobs_locked_by_workers",
        "jobs",
        "workers",
        ["locked_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_constraint(
        "fk_jobs_locked_by_workers",
        "jobs",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_jobs_status_lease_expiry",
        table_name="jobs",
    )

    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "locked_by")
