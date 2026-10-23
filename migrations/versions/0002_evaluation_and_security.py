"""Deleted-case lineage, reviewed answer points, and shared anonymous usage budget."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "faers_deletion",
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("dataset.id"), primary_key=True),
        sa.Column("case_id", sa.String(), primary_key=True),
        sa.Column("available_at", sa.Date(), primary_key=True),
        sa.Column("release", sa.String(), nullable=False),
    )
    op.add_column(
        "evaluation_case",
        sa.Column(
            "expected_answer_points", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )
    op.create_table(
        "request_budget",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("request_budget")
    op.drop_column("evaluation_case", "expected_answer_points")
    op.drop_table("faers_deletion")
