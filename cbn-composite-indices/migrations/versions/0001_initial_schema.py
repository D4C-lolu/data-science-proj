"""Create initial users and index runs tables.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    op.create_table(
        "index_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("index_type", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("upload_key", sa.String(length=255), nullable=False),
        sa.Column("result_key", sa.String(length=255), nullable=True),
        sa.Column("result_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "index_type IN ('BCI', 'CCI', 'HFCI', 'IPI', 'LMCI')",
            name="ck_index_runs_index_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_index_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_index_runs_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_index_runs"),
        sa.UniqueConstraint("upload_key", name="uq_index_runs_upload_key"),
        sa.UniqueConstraint("result_key", name="uq_index_runs_result_key"),
    )
    op.create_index("ix_index_runs_user_id", "index_runs", ["user_id"])
    op.create_index("ix_index_runs_status", "index_runs", ["status"])
    op.create_index("ix_index_runs_created_at", "index_runs", ["created_at"])


def downgrade():
    op.drop_index("ix_index_runs_created_at", table_name="index_runs")
    op.drop_index("ix_index_runs_status", table_name="index_runs")
    op.drop_index("ix_index_runs_user_id", table_name="index_runs")
    op.drop_table("index_runs")
    op.drop_table("users")
