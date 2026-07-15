"""Add Phase 1 calculation rule extraction persistence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0003"
down_revision: Union[str, None] = "20260715_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "calculation_rule_extractions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("workbook_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("inventory_version", sa.String(length=64), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("ir_version", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("function_registry_version", sa.String(length=64), nullable=False),
        sa.Column("semantics_profile", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.CHAR(length=64), nullable=False),
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
        _timestamp(),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warning', 'failed')",
            name="ck_calc_rule_extractions_status",
        ),
        sa.CheckConstraint(
            "length(configuration_hash) = 64",
            name="ck_calc_rule_extractions_configuration_hash",
        ),
        sa.ForeignKeyConstraint(
            ["workbook_version_id"],
            ["workbook_versions.id"],
            name="fk_calc_rule_extractions_workbook",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="fk_calc_rule_extractions_model",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "workbook_version_id",
            "compiler_version",
            "engine_version",
            "semantics_profile",
            "configuration_hash",
            name="uq_calc_rule_extractions_identity",
        ),
    )
    op.create_index(
        "ix_calc_rule_extractions_model_created",
        "calculation_rule_extractions",
        ["model_version_id", "created_at"],
    )
    op.create_index(
        "ix_calc_rule_extractions_workbook_status",
        "calculation_rule_extractions",
        ["workbook_version_id", "status"],
    )

    op.create_table(
        "workbook_formula_cells",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("workbook_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("sheet_position", sa.Integer(), nullable=False),
        sa.Column("sheet_state", sa.String(length=32), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("column_index", sa.Integer(), nullable=False),
        sa.Column("cell_address", sa.String(length=32), nullable=False),
        sa.Column("exact_formula", sa.Text(), nullable=False),
        sa.Column("formula_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("formula_kind", sa.String(length=32), nullable=False),
        sa.Column("special_range", sa.String(length=64), nullable=True),
        sa.Column("special_metadata_json", sa.JSON(), nullable=True),
        sa.Column("cached_value_json", sa.JSON(), nullable=True),
        sa.Column("cached_value_type", sa.String(length=32), nullable=False),
        sa.Column("cache_status", sa.String(length=32), nullable=False),
        sa.Column("cache_freshness", sa.String(length=32), nullable=False),
        sa.Column("number_format", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(length=16), nullable=True),
        sa.Column("inventory_version", sa.String(length=64), nullable=False),
        _timestamp(),
        sa.CheckConstraint(
            "formula_kind IN ('scalar', 'array', 'data_table', 'unknown_special')",
            name="ck_workbook_formula_cells_kind",
        ),
        sa.CheckConstraint(
            "cache_status IN ('available', 'missing', 'unavailable')",
            name="ck_workbook_formula_cells_cache_status",
        ),
        sa.CheckConstraint(
            "cache_freshness IN ('missing', 'unknown', 'recalculation_required')",
            name="ck_workbook_formula_cells_cache_freshness",
        ),
        sa.CheckConstraint("row_index > 0", name="ck_workbook_formula_cells_row"),
        sa.CheckConstraint("column_index > 0", name="ck_workbook_formula_cells_column"),
        sa.CheckConstraint(
            "length(formula_sha256) = 64",
            name="ck_workbook_formula_cells_formula_hash",
        ),
        sa.ForeignKeyConstraint(
            ["workbook_version_id"],
            ["workbook_versions.id"],
            name="fk_workbook_formula_cells_workbook",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workbook_version_id",
            "sheet_position",
            "cell_address",
            name="uq_workbook_formula_cells_location",
        ),
    )
    op.create_index(
        "ix_workbook_formula_cells_location",
        "workbook_formula_cells",
        ["workbook_version_id", "sheet_position", "row_index", "column_index"],
    )
    op.create_index(
        "ix_workbook_formula_cells_hash",
        "workbook_formula_cells",
        ["formula_sha256"],
    )

    op.create_table(
        "executable_formula_rules",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("formula_cell_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("ir_version", sa.String(length=64), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("semantics_profile", sa.String(length=64), nullable=False),
        sa.Column("formula_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("normalized_signature", sa.Text(), nullable=True),
        sa.Column("normalized_signature_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("support_status", sa.String(length=32), nullable=False),
        sa.Column("ir_json", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("unsupported_constructs_json", sa.JSON(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        _timestamp(),
        sa.CheckConstraint(
            "parse_status IN ('not_attempted', 'parsed', 'syntax_error')",
            name="ck_executable_formula_rules_parse_status",
        ),
        sa.CheckConstraint(
            "support_status IN ('supported', 'unsupported', 'external_reference', 'special_formula')",
            name="ck_executable_formula_rules_support_status",
        ),
        sa.CheckConstraint(
            "(support_status = 'supported' AND ir_json IS NOT NULL) OR "
            "(support_status <> 'supported' AND ir_json IS NULL)",
            name="ck_executable_formula_rules_ir_support",
        ),
        sa.ForeignKeyConstraint(
            ["formula_cell_id"],
            ["workbook_formula_cells.id"],
            name="fk_executable_formula_rules_cell",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "formula_cell_id",
            "ir_version",
            "compiler_version",
            "semantics_profile",
            "formula_sha256",
            name="uq_executable_formula_rules_version",
        ),
    )
    op.create_index(
        "ix_executable_formula_rules_support_compiler",
        "executable_formula_rules",
        ["support_status", "compiler_version"],
    )
    op.create_index(
        "ix_executable_formula_rules_signature_hash",
        "executable_formula_rules",
        ["normalized_signature_hash"],
    )

    op.create_table(
        "formula_references",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("executable_formula_rule_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_token", sa.Text(), nullable=False),
        sa.Column("source_span_start", sa.Integer(), nullable=False),
        sa.Column("source_span_end", sa.Integer(), nullable=False),
        sa.Column("reference_kind", sa.String(length=32), nullable=False),
        sa.Column("target_classification", sa.String(length=32), nullable=False),
        sa.Column("target_sheet_name", sa.String(length=255), nullable=True),
        sa.Column("target_sheet_position", sa.Integer(), nullable=True),
        sa.Column("start_cell_address", sa.String(length=32), nullable=True),
        sa.Column("end_cell_address", sa.String(length=32), nullable=True),
        sa.Column("start_column_absolute", sa.Boolean(), nullable=False),
        sa.Column("start_row_absolute", sa.Boolean(), nullable=False),
        sa.Column("end_column_absolute", sa.Boolean(), nullable=True),
        sa.Column("end_row_absolute", sa.Boolean(), nullable=True),
        sa.Column("range_rows", sa.Integer(), nullable=True),
        sa.Column("range_columns", sa.Integer(), nullable=True),
        sa.Column("resolution_status", sa.String(length=32), nullable=False),
        sa.Column("warning_code", sa.String(length=100), nullable=True),
        _timestamp(),
        sa.CheckConstraint(
            "reference_kind IN ('cell', 'range')",
            name="ck_formula_references_kind",
        ),
        sa.CheckConstraint(
            "target_classification IN ('internal', 'external', 'unresolved')",
            name="ck_formula_references_target_classification",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('resolved_internal', 'external', 'missing_sheet', "
            "'invalid_address', 'unsupported')",
            name="ck_formula_references_resolution_status",
        ),
        sa.ForeignKeyConstraint(
            ["executable_formula_rule_id"],
            ["executable_formula_rules.id"],
            name="fk_formula_references_rule",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "executable_formula_rule_id",
            "ordinal",
            "source_span_start",
            "source_span_end",
            name="uq_formula_references_source_span",
        ),
    )
    op.create_index(
        "ix_formula_references_target",
        "formula_references",
        ["target_classification", "target_sheet_name", "start_cell_address"],
    )
    op.create_index(
        "ix_formula_references_rule",
        "formula_references",
        ["executable_formula_rule_id"],
    )

    op.create_table(
        "formula_canonical_mappings",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("calculation_rule_extraction_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("formula_cell_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("reference_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("mapping_role", sa.String(length=16), nullable=False),
        sa.Column("mapping_status", sa.String(length=16), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("financial_series_value_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        _timestamp(),
        sa.CheckConstraint(
            "mapping_role IN ('output', 'input')",
            name="ck_formula_canonical_mappings_role",
        ),
        sa.CheckConstraint(
            "mapping_status IN ('mapped', 'unmapped', 'ambiguous')",
            name="ck_formula_canonical_mappings_status",
        ),
        sa.CheckConstraint(
            "entity_kind IS NULL OR entity_kind IN ('parameter', 'financial_series')",
            name="ck_formula_canonical_mappings_entity_kind",
        ),
        sa.CheckConstraint(
            "(mapping_status = 'mapped' AND entity_kind IS NOT NULL AND entity_id IS NOT NULL) "
            "OR (mapping_status <> 'mapped' AND entity_kind IS NULL AND entity_id IS NULL)",
            name="ck_formula_canonical_mappings_target",
        ),
        sa.ForeignKeyConstraint(
            ["calculation_rule_extraction_id"],
            ["calculation_rule_extractions.id"],
            name="fk_formula_mappings_extraction",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["formula_cell_id"],
            ["workbook_formula_cells.id"],
            name="fk_formula_mappings_cell",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["formula_references.id"],
            name="fk_formula_mappings_reference",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "calculation_rule_extraction_id",
            "formula_cell_id",
            "reference_id",
            "mapping_role",
            name="uq_formula_canonical_mappings_occurrence",
        ),
    )
    op.create_index(
        "ix_formula_canonical_mappings_entity",
        "formula_canonical_mappings",
        ["calculation_rule_extraction_id", "entity_kind", "entity_id"],
    )
    op.create_index(
        "ix_formula_canonical_mappings_series_value",
        "formula_canonical_mappings",
        ["financial_series_value_id"],
    )
    op.create_index(
        "uq_formula_canonical_mappings_output",
        "formula_canonical_mappings",
        ["calculation_rule_extraction_id", "formula_cell_id"],
        unique=True,
        sqlite_where=sa.text("mapping_role = 'output'"),
        postgresql_where=sa.text("mapping_role = 'output'"),
    )

    op.create_table(
        "formula_execution_results",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("calculation_rule_extraction_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("formula_cell_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("expression_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("execution_status", sa.String(length=32), nullable=False),
        sa.Column("calculated_value_type", sa.String(length=32), nullable=True),
        sa.Column("calculated_value_json", sa.JSON(), nullable=True),
        sa.Column("excel_error_code", sa.String(length=32), nullable=True),
        sa.Column("engine_error_code", sa.String(length=100), nullable=True),
        sa.Column("direct_input_trace_json", sa.JSON(), nullable=True),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("semantics_profile", sa.String(length=64), nullable=False),
        sa.Column("cached_value_type", sa.String(length=32), nullable=True),
        sa.Column("cached_value_json", sa.JSON(), nullable=True),
        sa.Column("absolute_error", sa.Float(), nullable=True),
        sa.Column("relative_error", sa.Float(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("cached_value_freshness", sa.String(length=32), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "execution_status IN ('executed', 'not_executable', 'blocked_by_dependency', "
            "'cycle', 'execution_error')",
            name="ck_formula_results_execution_status",
        ),
        sa.CheckConstraint(
            "validation_status IN ('matched', 'mismatched', 'not_comparable', "
            "'no_cached_value', 'execution_error')",
            name="ck_formula_results_validation_status",
        ),
        sa.CheckConstraint(
            "cached_value_freshness IN ('missing', 'unknown', 'recalculation_required')",
            name="ck_formula_results_cache_freshness",
        ),
        sa.ForeignKeyConstraint(
            ["calculation_rule_extraction_id"],
            ["calculation_rule_extractions.id"],
            name="fk_formula_results_extraction",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["formula_cell_id"],
            ["workbook_formula_cells.id"],
            name="fk_formula_results_cell",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expression_id"],
            ["executable_formula_rules.id"],
            name="fk_formula_results_expression",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "calculation_rule_extraction_id",
            "formula_cell_id",
            name="uq_formula_results_extraction_cell",
        ),
    )
    op.create_index(
        "ix_formula_results_extraction_status",
        "formula_execution_results",
        ["calculation_rule_extraction_id", "execution_status"],
    )
    op.create_index(
        "ix_formula_results_extraction_validation",
        "formula_execution_results",
        ["calculation_rule_extraction_id", "validation_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_formula_results_extraction_validation", table_name="formula_execution_results")
    op.drop_index("ix_formula_results_extraction_status", table_name="formula_execution_results")
    op.drop_table("formula_execution_results")
    op.drop_index("uq_formula_canonical_mappings_output", table_name="formula_canonical_mappings")
    op.drop_index("ix_formula_canonical_mappings_series_value", table_name="formula_canonical_mappings")
    op.drop_index("ix_formula_canonical_mappings_entity", table_name="formula_canonical_mappings")
    op.drop_table("formula_canonical_mappings")
    op.drop_index("ix_formula_references_rule", table_name="formula_references")
    op.drop_index("ix_formula_references_target", table_name="formula_references")
    op.drop_table("formula_references")
    op.drop_index("ix_executable_formula_rules_signature_hash", table_name="executable_formula_rules")
    op.drop_index("ix_executable_formula_rules_support_compiler", table_name="executable_formula_rules")
    op.drop_table("executable_formula_rules")
    op.drop_index("ix_workbook_formula_cells_hash", table_name="workbook_formula_cells")
    op.drop_index("ix_workbook_formula_cells_location", table_name="workbook_formula_cells")
    op.drop_table("workbook_formula_cells")
    op.drop_index("ix_calc_rule_extractions_workbook_status", table_name="calculation_rule_extractions")
    op.drop_index("ix_calc_rule_extractions_model_created", table_name="calculation_rule_extractions")
    op.drop_table("calculation_rule_extractions")
