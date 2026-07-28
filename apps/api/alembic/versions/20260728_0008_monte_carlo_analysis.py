"""Add persisted Monte Carlo queue, configuration, and artifacts.

Revision ID: 20260728_0008
Revises: 20260728_0007
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_0008"
down_revision: Union[str, Sequence[str], None] = "20260728_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monte_carlo_runs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column(
            "baseline_calculation_run_id",
            sa.Uuid(as_uuid=False),
            nullable=False,
        ),
        sa.Column(
            "current_calculation_run_id",
            sa.Uuid(as_uuid=False),
            nullable=False,
        ),
        sa.Column("request_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("trial_count", sa.Integer(), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=False),
        sa.Column("method_version", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
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
            "status IN ('queued', 'running', 'completed', 'failed', "
            "'cancelled')",
            name="ck_monte_carlo_runs_status",
        ),
        sa.CheckConstraint(
            "trial_count BETWEEN 1 AND 50000",
            name="ck_monte_carlo_runs_trial_count",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_monte_carlo_runs_request_hash",
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
            ["baseline_calculation_run_id"],
            ["calculation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_calculation_run_id"],
            ["calculation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_hash",
            name="uq_monte_carlo_runs_request_hash",
        ),
        sa.UniqueConstraint(
            "model_version_id",
            "idempotency_key",
            name="uq_monte_carlo_runs_model_idempotency",
        ),
    )
    op.create_index(
        "ix_monte_carlo_runs_queue",
        "monte_carlo_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_monte_carlo_runs_model_created",
        "monte_carlo_runs",
        ["model_version_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "monte_carlo_input_configurations",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("monte_carlo_run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("correlation_matrix_json", sa.JSON(), nullable=False),
        sa.Column("selected_output_roles_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["monte_carlo_run_id"],
            ["monte_carlo_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monte_carlo_run_id",
            name="uq_monte_carlo_input_configurations_run",
        ),
    )
    op.create_table(
        "monte_carlo_result_artifacts",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("monte_carlo_run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("calibration_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["monte_carlo_run_id"],
            ["monte_carlo_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monte_carlo_run_id",
            name="uq_monte_carlo_result_artifacts_run",
        ),
    )


def downgrade() -> None:
    op.drop_table("monte_carlo_result_artifacts")
    op.drop_table("monte_carlo_input_configurations")
    op.drop_index(
        "ix_monte_carlo_runs_model_created",
        table_name="monte_carlo_runs",
    )
    op.drop_index(
        "ix_monte_carlo_runs_queue",
        table_name="monte_carlo_runs",
    )
    op.drop_table("monte_carlo_runs")
