"""Bounded anonymous session memory; no raw access tokens are persisted."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
    )
    op.create_index("ix_chat_session_expires_at", "chat_session", ["expires_at"])
    # Existing installations have a restricted runtime role; disposable CI databases do not.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""DO $$ BEGIN
          IF EXISTS (SELECT FROM pg_roles WHERE rolname='pharmaguard_runtime') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON chat_session TO pharmaguard_runtime;
          END IF;
        END $$""")


def downgrade() -> None:
    op.drop_table("chat_session")
