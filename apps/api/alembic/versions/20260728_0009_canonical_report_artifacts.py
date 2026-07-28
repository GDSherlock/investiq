"""Add canonical asynchronous report runs and immutable artifacts.

Revision ID: 20260728_0009
Revises: 20260728_0008
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_0009"
down_revision: Union[str, Sequence[str], None] = "20260728_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_report_runs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("calculation_run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column(
            "sensitivity_analysis_id",
            sa.Uuid(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "monte_carlo_run_id",
            sa.Uuid(as_uuid=False),
            nullable=True,
        ),
        sa.Column("template_id", sa.String(length=100), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("persona_id", sa.String(length=32), nullable=False),
        sa.Column("persona_json", sa.JSON(), nullable=False),
        sa.Column("frozen_evidence_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("request_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("runtime_ms", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_canonical_report_runs_status",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_canonical_report_runs_request_hash",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_canonical_report_runs_evidence_hash",
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
            ["calculation_run_id"],
            ["calculation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sensitivity_analysis_id"],
            ["calculation_sensitivity_analyses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["monte_carlo_run_id"],
            ["monte_carlo_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_hash",
            name="uq_canonical_report_runs_request_hash",
        ),
        sa.UniqueConstraint(
            "model_version_id",
            "idempotency_key",
            name="uq_canonical_report_runs_model_idempotency",
        ),
    )
    op.create_index(
        "ix_canonical_report_runs_queue",
        "canonical_report_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_report_runs_model_created",
        "canonical_report_runs",
        ["model_version_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "canonical_report_artifacts",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("report_run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("artifact_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_canonical_report_artifacts_evidence_hash",
        ),
        sa.ForeignKeyConstraint(
            ["report_run_id"],
            ["canonical_report_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_run_id",
            name="uq_canonical_report_artifacts_run",
        ),
    )


def downgrade() -> None:
    op.drop_table("canonical_report_artifacts")
    op.drop_index(
        "ix_canonical_report_runs_model_created",
        table_name="canonical_report_runs",
    )
    op.drop_index(
        "ix_canonical_report_runs_queue",
        table_name="canonical_report_runs",
    )
    op.drop_table("canonical_report_runs")
