"""Add reviewed semantic bindings for persisted analysis views.

Revision ID: 20260728_0007
Revises: 20260727_0006
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_0007"
down_revision: Union[str, Sequence[str], None] = "20260727_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PARAMETER_ROLES = (
    "discount_rate",
    "project_irr_hurdle",
    "equity_irr_hurdle",
    "dscr_covenant",
    "debt_ratio",
    "equity_ratio",
)

_LEGACY_SERIES_ROLES = (
    "project_irr",
    "equity_irr",
    "npv",
    "minimum_dscr",
    "average_dscr",
    "total_project_cost",
    "total_capex",
    "total_debt",
    "peak_debt",
    "average_ebitda_margin",
    "payback_period",
    "equity_multiple",
    "revenue",
    "opex",
    "fixed_opex",
    "variable_opex",
    "ebitda",
    "cfads",
    "debt_service",
    "debt_balance",
    "opening_debt",
    "closing_debt",
    "principal_repayment",
    "interest_expense",
    "cash_flow",
    "equity_cash_flow",
    "tax",
    "net_generation",
    "power_price",
    "unclassified",
)

_SERIES_ROLES = (
    *_LEGACY_SERIES_ROLES,
    "project_free_cash_flow",
    "operating_cash_flow",
    "dscr",
    "dscr_covenant",
    "capex",
    "total_equity",
    "debt_ratio",
    "equity_ratio",
    "debt_to_equity_ratio",
)

_BINDING_ROLES = (
    "project_irr",
    "equity_irr",
    "project_npv",
    "equity_npv",
    "payback_period",
    "minimum_dscr",
    "average_dscr",
    "equity_multiple",
    "debt_to_equity_ratio",
    "discount_rate",
    "project_irr_hurdle",
    "equity_irr_hurdle",
    "dscr_covenant",
    "revenue",
    "ebitda",
    "cfads",
    "project_free_cash_flow",
    "equity_cash_flow",
    "operating_cash_flow",
    "debt_service",
    "dscr",
    "closing_debt",
    "capex",
    "interest_expense",
    "principal_repayment",
    "total_debt",
    "total_equity",
    "debt_ratio",
    "equity_ratio",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    with op.batch_alter_table("financial_series") as batch_op:
        batch_op.drop_constraint(
            "ck_financial_series_business_role",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_financial_series_business_role",
            "business_role IS NULL OR "
            f"business_role IN ({_sql_values(_SERIES_ROLES)})",
        )
    with op.batch_alter_table("model_parameters") as batch_op:
        batch_op.add_column(
            sa.Column("business_role", sa.String(length=64), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "stochastic_eligible",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )
        batch_op.create_check_constraint(
            "ck_model_parameters_business_role",
            "business_role IS NULL OR "
            f"business_role IN ({_sql_values(_PARAMETER_ROLES)})",
        )
    op.create_table(
        "model_semantic_bindings",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("semantic_role", sa.String(length=64), nullable=False),
        sa.Column("canonical_output_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("financial_series_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("model_parameter_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column(
            "binding_source",
            sa.String(length=32),
            server_default="reviewed",
            nullable=False,
        ),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            f"semantic_role IN ({_sql_values(_BINDING_ROLES)})",
            name="ck_model_semantic_bindings_role",
        ),
        sa.CheckConstraint(
            "binding_source IN ('extracted', 'reviewed')",
            name="ck_model_semantic_bindings_source",
        ),
        sa.CheckConstraint(
            "("
            "canonical_output_id IS NOT NULL AND "
            "financial_series_id IS NULL AND model_parameter_id IS NULL"
            ") OR ("
            "canonical_output_id IS NULL AND "
            "financial_series_id IS NOT NULL AND model_parameter_id IS NULL"
            ") OR ("
            "canonical_output_id IS NULL AND "
            "financial_series_id IS NULL AND model_parameter_id IS NOT NULL"
            ")",
            name="ck_model_semantic_bindings_exactly_one_entity",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_output_id"],
            ["canonical_outputs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["financial_series_id"],
            ["financial_series.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_parameter_id"],
            ["model_parameters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "semantic_role",
            name="uq_model_semantic_bindings_model_role",
        ),
    )
    op.create_index(
        "ix_model_semantic_bindings_model_role",
        "model_semantic_bindings",
        ["model_version_id", "semantic_role"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_semantic_bindings_model_role",
        table_name="model_semantic_bindings",
    )
    op.drop_table("model_semantic_bindings")
    with op.batch_alter_table("model_parameters") as batch_op:
        batch_op.drop_constraint(
            "ck_model_parameters_business_role",
            type_="check",
        )
        batch_op.drop_column("stochastic_eligible")
        batch_op.drop_column("business_role")
    with op.batch_alter_table("financial_series") as batch_op:
        batch_op.drop_constraint(
            "ck_financial_series_business_role",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_financial_series_business_role",
            "business_role IS NULL OR "
            f"business_role IN ({_sql_values(_LEGACY_SERIES_ROLES)})",
        )
