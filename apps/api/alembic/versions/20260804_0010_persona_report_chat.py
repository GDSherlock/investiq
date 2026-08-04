"""Add persistent persona report conversations.

Revision ID: 20260804_0010
Revises: 20260728_0009
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260804_0010"
down_revision: Union[str, Sequence[str], None] = "20260728_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_chat_threads",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_key", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "owner_key",
            name="uq_report_chat_threads_model_owner",
        ),
    )
    op.create_table(
        "report_chat_messages",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("thread_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column(
            "response_to_message_id",
            sa.Uuid(as_uuid=False),
            nullable=True,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("persona_id", sa.String(length=2), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column(
            "calculation_run_id",
            sa.Uuid(as_uuid=False),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_report_chat_messages_role",
        ),
        sa.CheckConstraint(
            "kind IN ('text', 'report', 'error')",
            name="ck_report_chat_messages_kind",
        ),
        sa.CheckConstraint(
            "persona_id IN ('IM', 'CF', 'BD', 'FA', 'PO')",
            name="ck_report_chat_messages_persona",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["report_chat_threads.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["response_to_message_id"],
            ["report_chat_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "idempotency_key",
            name="uq_report_chat_messages_thread_idempotency",
        ),
        sa.UniqueConstraint(
            "response_to_message_id",
            name="uq_report_chat_messages_response_to",
        ),
    )
    op.create_index(
        "ix_report_chat_messages_thread_created",
        "report_chat_messages",
        ["thread_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_report_chat_messages_thread_created",
        table_name="report_chat_messages",
    )
    op.drop_table("report_chat_messages")
    op.drop_table("report_chat_threads")
