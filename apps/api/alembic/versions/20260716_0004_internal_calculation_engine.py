"""Add Phase 2 internal calculation engine persistence.

Revision ID: 20260716_0004
Revises: 20260715_0003
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0004"
down_revision: Union[str, Sequence[str], None] = "20260715_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "workbook_named_expressions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("workbook_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_sheet_name", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("definition_text", sa.Text(), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("resolution_status", sa.String(length=32), nullable=False),
        sa.Column("resolved_targets_json", sa.JSON(), nullable=True),
        sa.Column("definition_sha256", sa.CHAR(length=64), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "scope_type IN ('workbook', 'sheet')",
            name="ck_workbook_named_expressions_scope_type",
        ),
        sa.CheckConstraint(
            "target_kind IN ('constant', 'cell', 'range', 'formula', 'unsupported')",
            name="ck_workbook_named_expressions_target_kind",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('resolved', 'unsupported', 'external', 'invalid')",
            name="ck_workbook_named_expressions_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["workbook_version_id"],
            ["workbook_versions.id"],
            name="fk_workbook_named_expressions_workbook",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workbook_version_id",
            "scope_type",
            "scope_sheet_name",
            "name",
            name="uq_workbook_named_expressions_scope",
        ),
    )
    op.create_index(
        "ix_workbook_named_expressions_workbook_name",
        "workbook_named_expressions",
        ["workbook_version_id", "name"],
    )

    op.create_table(
        "calculation_graph_versions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("workbook_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("ir_version", sa.String(length=64), nullable=False),
        sa.Column("function_registry_version", sa.String(length=64), nullable=False),
        sa.Column("semantics_profile", sa.String(length=64), nullable=False),
        sa.Column("compiler_manifest_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("content_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("topological_layers_json", sa.JSON(), nullable=False),
        sa.Column("volatile_nodes_json", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "node_count >= 0", name="ck_calculation_graph_versions_nodes"
        ),
        sa.CheckConstraint(
            "edge_count >= 0", name="ck_calculation_graph_versions_edges"
        ),
        sa.CheckConstraint(
            "length(compiler_manifest_hash) = 64",
            name="ck_calculation_graph_versions_manifest_hash",
        ),
        sa.CheckConstraint(
            "length(content_fingerprint) = 64",
            name="ck_calculation_graph_versions_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["workbook_version_id"],
            ["workbook_versions.id"],
            name="fk_calculation_graph_versions_workbook",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workbook_version_id",
            "compiler_manifest_hash",
            name="uq_calculation_graph_versions_manifest",
        ),
    )
    op.create_index(
        "ix_calculation_graph_versions_workbook_created",
        "calculation_graph_versions",
        ["workbook_version_id", "created_at"],
    )

    op.create_table(
        "calculation_graph_components",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(length=48), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("member_formula_cells_json", sa.JSON(), nullable=False),
        sa.Column("topological_layer", sa.Integer(), nullable=True),
        sa.Column("iteration_enabled", sa.Boolean(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "classification IN ('acyclic_singleton', 'self_reference', "
            "'multi_cell_cycle', 'eligible_iterative_component', 'blocked_unsupported')",
            name="ck_calculation_graph_components_classification",
        ),
        sa.CheckConstraint(
            "member_count > 0", name="ck_calculation_graph_components_members"
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["calculation_graph_versions.id"],
            name="fk_calculation_graph_components_graph",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "graph_version_id",
            "ordinal",
            name="uq_calculation_graph_components_ordinal",
        ),
    )
    op.create_index(
        "ix_calculation_graph_components_graph_class",
        "calculation_graph_components",
        ["graph_version_id", "classification"],
    )

    op.create_table(
        "grouped_calculation_rules",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("grouping_profile", sa.String(length=64), nullable=False),
        sa.Column("group_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("normalized_expression", sa.Text(), nullable=False),
        sa.Column("orientation", sa.String(length=16), nullable=False),
        sa.Column("exceptions_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("approval_status", sa.String(length=16), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("semantics_profile", sa.String(length=64), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "orientation IN ('horizontal', 'vertical')",
            name="ck_grouped_calculation_rules_orientation",
        ),
        sa.CheckConstraint(
            "approval_status IN ('unreviewed', 'approved', 'rejected')",
            name="ck_grouped_calculation_rules_approval",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_grouped_calculation_rules_confidence",
        ),
        sa.CheckConstraint(
            "length(group_fingerprint) = 64",
            name="ck_grouped_calculation_rules_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="fk_grouped_calculation_rules_model",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["calculation_graph_versions.id"],
            name="fk_grouped_calculation_rules_graph",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "grouping_profile",
            "group_fingerprint",
            name="uq_grouped_calculation_rules_identity",
        ),
    )
    op.create_index(
        "ix_grouped_calculation_rules_model_created",
        "grouped_calculation_rules",
        ["model_version_id", "created_at"],
    )

    op.create_table(
        "calculation_rule_members",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("grouped_rule_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("formula_cell_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("expression_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("period_offset", sa.Integer(), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("cell_address", sa.String(length=32), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["grouped_rule_id"],
            ["grouped_calculation_rules.id"],
            name="fk_calculation_rule_members_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["formula_cell_id"],
            ["workbook_formula_cells.id"],
            name="fk_calculation_rule_members_cell",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expression_id"],
            ["executable_formula_rules.id"],
            name="fk_calculation_rule_members_expression",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grouped_rule_id", "ordinal", name="uq_calculation_rule_members_ordinal"
        ),
        sa.UniqueConstraint(
            "grouped_rule_id",
            "formula_cell_id",
            name="uq_calculation_rule_members_cell",
        ),
    )
    op.create_index(
        "ix_calculation_rule_members_formula",
        "calculation_rule_members",
        ["formula_cell_id"],
    )

    op.create_table(
        "calculation_rule_dependencies",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("grouped_rule_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("dependency_role", sa.String(length=16), nullable=False),
        sa.Column("dependency_key", sa.String(length=512), nullable=False),
        sa.Column("canonical_entity_kind", sa.String(length=32), nullable=True),
        sa.Column("canonical_entity_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("source_formula_cell_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("source_reference_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "dependency_role IN ('input', 'output')",
            name="ck_calculation_rule_dependencies_role",
        ),
        sa.CheckConstraint(
            "canonical_entity_kind IS NULL OR canonical_entity_kind IN ('parameter', 'financial_series')",
            name="ck_calculation_rule_dependencies_entity_kind",
        ),
        sa.ForeignKeyConstraint(
            ["grouped_rule_id"],
            ["grouped_calculation_rules.id"],
            name="fk_calculation_rule_dependencies_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_formula_cell_id"],
            ["workbook_formula_cells.id"],
            name="fk_calculation_rule_dependencies_cell",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["formula_references.id"],
            name="fk_calculation_rule_dependencies_reference",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grouped_rule_id",
            "dependency_role",
            "dependency_key",
            name="uq_calculation_rule_dependencies_identity",
        ),
    )
    op.create_index(
        "ix_calculation_rule_dependencies_canonical",
        "calculation_rule_dependencies",
        ["canonical_entity_kind", "canonical_entity_id"],
    )

    op.create_table(
        "calculation_runs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("base_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("function_registry_version", sa.String(length=64), nullable=False),
        sa.Column("semantics_profile", sa.String(length=64), nullable=False),
        sa.Column("normalized_override_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("run_policy_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("overrides_json", sa.JSON(), nullable=False),
        sa.Column("run_policy_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'completed_with_warning', "
            "'failed', 'cancelled')",
            name="ck_calculation_runs_status",
        ),
        sa.CheckConstraint(
            "length(normalized_override_hash) = 64",
            name="ck_calculation_runs_override_hash",
        ),
        sa.CheckConstraint(
            "length(run_policy_hash) = 64",
            name="ck_calculation_runs_policy_hash",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="fk_calculation_runs_model",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["calculation_graph_versions.id"],
            name="fk_calculation_runs_graph",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_run_id"],
            ["calculation_runs.id"],
            name="fk_calculation_runs_base_run",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "graph_version_id",
            "function_registry_version",
            "normalized_override_hash",
            "run_policy_hash",
            name="uq_calculation_runs_identity",
        ),
    )
    op.create_index(
        "ix_calculation_runs_model_created",
        "calculation_runs",
        ["model_version_id", "created_at"],
    )
    op.create_index(
        "ix_calculation_runs_graph_status",
        "calculation_runs",
        ["graph_version_id", "status"],
    )

    op.create_table(
        "calculation_run_values",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("calculation_run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("formula_cell_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("expression_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("execution_status", sa.String(length=32), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("excel_error_code", sa.String(length=32), nullable=True),
        sa.Column("engine_error_code", sa.String(length=100), nullable=True),
        sa.Column("reused_from_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("direct_input_trace_json", sa.JSON(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "execution_status IN ('executed', 'not_executable', 'blocked_by_dependency', "
            "'cycle', 'execution_error', 'reused', 'cached_comparison_only', "
            "'iteration_converged', 'iteration_not_converged', 'unavailable')",
            name="ck_calculation_run_values_execution_status",
        ),
        sa.CheckConstraint(
            "validation_status IN ('matched', 'mismatched', 'not_comparable', "
            "'no_cached_value', 'execution_error')",
            name="ck_calculation_run_values_validation_status",
        ),
        sa.ForeignKeyConstraint(
            ["calculation_run_id"],
            ["calculation_runs.id"],
            name="fk_calculation_run_values_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["formula_cell_id"],
            ["workbook_formula_cells.id"],
            name="fk_calculation_run_values_cell",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expression_id"],
            ["executable_formula_rules.id"],
            name="fk_calculation_run_values_expression",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reused_from_run_id"],
            ["calculation_runs.id"],
            name="fk_calculation_run_values_reused_run",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "calculation_run_id",
            "formula_cell_id",
            name="uq_calculation_run_values_cell",
        ),
    )
    op.create_index(
        "ix_calculation_run_values_run_status",
        "calculation_run_values",
        ["calculation_run_id", "execution_status"],
    )
    op.create_index(
        "ix_calculation_run_values_formula",
        "calculation_run_values",
        ["formula_cell_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_calculation_run_values_formula", table_name="calculation_run_values")
    op.drop_index("ix_calculation_run_values_run_status", table_name="calculation_run_values")
    op.drop_table("calculation_run_values")
    op.drop_index("ix_calculation_runs_graph_status", table_name="calculation_runs")
    op.drop_index("ix_calculation_runs_model_created", table_name="calculation_runs")
    op.drop_table("calculation_runs")
    op.drop_index(
        "ix_calculation_rule_dependencies_canonical",
        table_name="calculation_rule_dependencies",
    )
    op.drop_table("calculation_rule_dependencies")
    op.drop_index("ix_calculation_rule_members_formula", table_name="calculation_rule_members")
    op.drop_table("calculation_rule_members")
    op.drop_index(
        "ix_grouped_calculation_rules_model_created",
        table_name="grouped_calculation_rules",
    )
    op.drop_table("grouped_calculation_rules")
    op.drop_index(
        "ix_calculation_graph_components_graph_class",
        table_name="calculation_graph_components",
    )
    op.drop_table("calculation_graph_components")
    op.drop_index(
        "ix_calculation_graph_versions_workbook_created",
        table_name="calculation_graph_versions",
    )
    op.drop_table("calculation_graph_versions")
    op.drop_index(
        "ix_workbook_named_expressions_workbook_name",
        table_name="workbook_named_expressions",
    )
    op.drop_table("workbook_named_expressions")
