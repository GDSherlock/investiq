"""Add compact persisted sensitivity analysis artifacts.

Revision ID: 20260727_0006
Revises: 20260720_0005
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0006"
down_revision: Union[str, Sequence[str], None] = "20260720_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calculation_sensitivity_analyses",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column(
            "comparison_baseline_run_id",
            sa.Uuid(as_uuid=False),
            nullable=False,
        ),
        sa.Column("current_run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column(
            "function_registry_version",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("semantics_profile", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_calculation_sensitivity_analyses_status",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_calculation_sensitivity_analyses_request_hash",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["calculation_graph_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_baseline_run_id"],
            ["calculation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_run_id"],
            ["calculation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_hash",
            name="uq_calculation_sensitivity_analyses_request_hash",
        ),
    )
    op.create_index(
        "ix_calculation_sensitivity_model_created",
        "calculation_sensitivity_analyses",
        ["model_version_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calculation_sensitivity_model_created",
        table_name="calculation_sensitivity_analyses",
    )
    op.drop_table("calculation_sensitivity_analyses")
