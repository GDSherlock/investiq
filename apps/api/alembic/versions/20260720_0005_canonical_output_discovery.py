"""Add stable canonical output definitions for calculation discovery.

Revision ID: 20260720_0005
Revises: 20260716_0004
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0005"
down_revision: Union[str, Sequence[str], None] = "20260716_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BUSINESS_OUTPUT_ROLES_SQL = ", ".join(
    f"'{role}'"
    for role in (
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
)


def upgrade() -> None:
    with op.batch_alter_table("financial_series") as batch_op:
        batch_op.add_column(
            sa.Column("business_role", sa.String(length=64), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_financial_series_business_role",
            "business_role IS NULL OR "
            f"business_role IN ({_BUSINESS_OUTPUT_ROLES_SQL})",
        )
        batch_op.create_index(
            "ix_financial_series_model_business_role",
            ["model_version_id", "business_role"],
            unique=False,
        )

    op.create_table(
        "canonical_outputs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("llm_candidate_alias", sa.String(length=255), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=True),
        sa.Column("business_role", sa.String(length=64), nullable=False),
        sa.Column("submitted_role", sa.String(length=64), nullable=False),
        sa.Column("validated_role", sa.String(length=64), nullable=False),
        sa.Column("raw_value_json", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("scenario", sa.String(length=100), nullable=True),
        sa.Column("period_json", sa.JSON(), nullable=True),
        sa.Column("source_sheet", sa.String(length=255), nullable=False),
        sa.Column("source_cell", sa.String(length=32), nullable=False),
        sa.Column("exact_formula", sa.Text(), nullable=True),
        sa.Column("formula_status", sa.String(length=64), nullable=False),
        sa.Column("source_validation_status", sa.String(length=32), nullable=False),
        sa.Column("role_validation_status", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("data_type", sa.String(length=16), nullable=True),
        sa.Column("number_format", sa.Text(), nullable=True),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column("validation_confidence", sa.Float(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column("validation_warnings_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_kind = 'canonical_output'",
            name="ck_canonical_outputs_entity_kind",
        ),
        sa.CheckConstraint(
            f"business_role IN ({_BUSINESS_OUTPUT_ROLES_SQL})",
            name="ck_canonical_outputs_business_role",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "source_sheet",
            "source_cell",
            name="uq_canonical_outputs_source_cell",
        ),
    )
    op.create_index(
        "ix_canonical_outputs_model_role",
        "canonical_outputs",
        ["model_version_id", "business_role"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canonical_outputs_model_role",
        table_name="canonical_outputs",
    )
    op.drop_table("canonical_outputs")

    with op.batch_alter_table("financial_series") as batch_op:
        batch_op.drop_index("ix_financial_series_model_business_role")
        batch_op.drop_constraint(
            "ck_financial_series_business_role",
            type_="check",
        )
        batch_op.drop_column("business_role")
