"""allow cancelled job status

Revision ID: eeba8a7e388c
Revises: ad0d4807b13a
"""

from collections.abc import Sequence

from alembic import op

revision: str = "eeba8a7e388c"
down_revision: str | Sequence[str] | None = "ad0d4807b13a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_jobs_status",
        "jobs",
        type_="check",
    )

    op.create_check_constraint(
        "ck_jobs_status",
        "jobs",
        """
        status IN (
            'pending',
            'running',
            'completed',
            'retrying',
            'failed',
            'dead_letter',
            'cancelled'
        )
        """,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_jobs_status",
        "jobs",
        type_="check",
    )

    op.create_check_constraint(
        "ck_jobs_status",
        "jobs",
        """
        status IN (
            'pending',
            'running',
            'completed',
            'retrying',
            'failed',
            'dead_letter'
        )
        """,
    )
