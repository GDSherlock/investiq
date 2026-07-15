"""Additive SQLAlchemy models for Phase 1 calculation rule extraction."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
    UniqueConstraint,
    Uuid,
)

from ..database import Base
from .. import model_extraction_models as _model_extraction_models  # noqa: F401


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CalculationRuleExtraction(Base):
    __tablename__ = "calculation_rule_extractions"
    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "workbook_version_id",
            "compiler_version",
            "engine_version",
            "semantics_profile",
            "configuration_hash",
            name="uq_calc_rule_extractions_identity",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warning', 'failed')",
            name="ck_calc_rule_extractions_status",
        ),
        CheckConstraint(
            "length(configuration_hash) = 64",
            name="ck_calc_rule_extractions_configuration_hash",
        ),
        Index(
            "ix_calc_rule_extractions_model_created",
            "model_version_id",
            "created_at",
        ),
        Index(
            "ix_calc_rule_extractions_workbook_status",
            "workbook_version_id",
            "status",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    workbook_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_versions.id",
            ondelete="RESTRICT",
            name="fk_calc_rule_extractions_workbook",
        ),
        nullable=False,
    )
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "model_versions.id",
            ondelete="RESTRICT",
            name="fk_calc_rule_extractions_model",
        ),
        nullable=False,
    )
    inventory_version = Column(String(64), nullable=False)
    compiler_version = Column(String(64), nullable=False)
    ir_version = Column(String(64), nullable=False)
    engine_version = Column(String(64), nullable=False)
    function_registry_version = Column(String(64), nullable=False)
    semantics_profile = Column(String(64), nullable=False)
    configuration_hash = Column(CHAR(64), nullable=False)
    status = Column(String(32), nullable=False)
    summary_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class WorkbookFormulaCellRecord(Base):
    __tablename__ = "workbook_formula_cells"
    __table_args__ = (
        UniqueConstraint(
            "workbook_version_id",
            "sheet_position",
            "cell_address",
            name="uq_workbook_formula_cells_location",
        ),
        CheckConstraint(
            "formula_kind IN ('scalar', 'array', 'data_table', 'unknown_special')",
            name="ck_workbook_formula_cells_kind",
        ),
        CheckConstraint(
            "cache_status IN ('available', 'missing', 'unavailable')",
            name="ck_workbook_formula_cells_cache_status",
        ),
        CheckConstraint(
            "cache_freshness IN ('missing', 'unknown', 'recalculation_required')",
            name="ck_workbook_formula_cells_cache_freshness",
        ),
        CheckConstraint("row_index > 0", name="ck_workbook_formula_cells_row"),
        CheckConstraint("column_index > 0", name="ck_workbook_formula_cells_column"),
        CheckConstraint(
            "length(formula_sha256) = 64",
            name="ck_workbook_formula_cells_formula_hash",
        ),
        Index(
            "ix_workbook_formula_cells_location",
            "workbook_version_id",
            "sheet_position",
            "row_index",
            "column_index",
        ),
        Index("ix_workbook_formula_cells_hash", "formula_sha256"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    workbook_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_versions.id",
            ondelete="RESTRICT",
            name="fk_workbook_formula_cells_workbook",
        ),
        nullable=False,
    )
    sheet_name = Column(String(255), nullable=False)
    sheet_position = Column(Integer, nullable=False)
    sheet_state = Column(String(32), nullable=False)
    row_index = Column(Integer, nullable=False)
    column_index = Column(Integer, nullable=False)
    cell_address = Column(String(32), nullable=False)
    exact_formula = Column(Text, nullable=False)
    formula_sha256 = Column(CHAR(64), nullable=False)
    formula_kind = Column(String(32), nullable=False)
    special_range = Column(String(64), nullable=True)
    special_metadata_json = Column(JSON, nullable=True)
    cached_value_json = Column(JSON, nullable=True)
    cached_value_type = Column(String(32), nullable=False)
    cache_status = Column(String(32), nullable=False)
    cache_freshness = Column(String(32), nullable=False)
    number_format = Column(Text, nullable=True)
    data_type = Column(String(16), nullable=True)
    inventory_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class ExecutableFormulaRule(Base):
    __tablename__ = "executable_formula_rules"
    __table_args__ = (
        UniqueConstraint(
            "formula_cell_id",
            "ir_version",
            "compiler_version",
            "semantics_profile",
            "formula_sha256",
            name="uq_executable_formula_rules_version",
        ),
        CheckConstraint(
            "parse_status IN ('not_attempted', 'parsed', 'syntax_error')",
            name="ck_executable_formula_rules_parse_status",
        ),
        CheckConstraint(
            "support_status IN ('supported', 'unsupported', 'external_reference', 'special_formula')",
            name="ck_executable_formula_rules_support_status",
        ),
        CheckConstraint(
            "(support_status = 'supported' AND ir_json IS NOT NULL) OR "
            "(support_status <> 'supported' AND ir_json IS NULL)",
            name="ck_executable_formula_rules_ir_support",
        ),
        Index(
            "ix_executable_formula_rules_support_compiler",
            "support_status",
            "compiler_version",
        ),
        Index(
            "ix_executable_formula_rules_signature_hash",
            "normalized_signature_hash",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    formula_cell_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_formula_cells.id",
            ondelete="CASCADE",
            name="fk_executable_formula_rules_cell",
        ),
        nullable=False,
    )
    ir_version = Column(String(64), nullable=False)
    compiler_version = Column(String(64), nullable=False)
    semantics_profile = Column(String(64), nullable=False)
    formula_sha256 = Column(CHAR(64), nullable=False)
    normalized_signature = Column(Text, nullable=True)
    normalized_signature_hash = Column(CHAR(64), nullable=True)
    parse_status = Column(String(32), nullable=False)
    support_status = Column(String(32), nullable=False)
    ir_json = Column(JSON(none_as_null=True), nullable=True)
    unsupported_constructs_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class FormulaReferenceRecord(Base):
    __tablename__ = "formula_references"
    __table_args__ = (
        UniqueConstraint(
            "executable_formula_rule_id",
            "ordinal",
            "source_span_start",
            "source_span_end",
            name="uq_formula_references_source_span",
        ),
        CheckConstraint(
            "reference_kind IN ('cell', 'range')",
            name="ck_formula_references_kind",
        ),
        CheckConstraint(
            "target_classification IN ('internal', 'external', 'unresolved')",
            name="ck_formula_references_target_classification",
        ),
        CheckConstraint(
            "resolution_status IN ('resolved_internal', 'external', 'missing_sheet', "
            "'invalid_address', 'unsupported')",
            name="ck_formula_references_resolution_status",
        ),
        Index(
            "ix_formula_references_target",
            "target_classification",
            "target_sheet_name",
            "start_cell_address",
        ),
        Index("ix_formula_references_rule", "executable_formula_rule_id"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    executable_formula_rule_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "executable_formula_rules.id",
            ondelete="CASCADE",
            name="fk_formula_references_rule",
        ),
        nullable=False,
    )
    ordinal = Column(Integer, nullable=False)
    source_token = Column(Text, nullable=False)
    source_span_start = Column(Integer, nullable=False)
    source_span_end = Column(Integer, nullable=False)
    reference_kind = Column(String(32), nullable=False)
    target_classification = Column(String(32), nullable=False)
    target_sheet_name = Column(String(255), nullable=True)
    target_sheet_position = Column(Integer, nullable=True)
    start_cell_address = Column(String(32), nullable=True)
    end_cell_address = Column(String(32), nullable=True)
    start_column_absolute = Column(Boolean, nullable=False)
    start_row_absolute = Column(Boolean, nullable=False)
    end_column_absolute = Column(Boolean, nullable=True)
    end_row_absolute = Column(Boolean, nullable=True)
    range_rows = Column(Integer, nullable=True)
    range_columns = Column(Integer, nullable=True)
    resolution_status = Column(String(32), nullable=False)
    warning_code = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class FormulaCanonicalMapping(Base):
    __tablename__ = "formula_canonical_mappings"
    __table_args__ = (
        UniqueConstraint(
            "calculation_rule_extraction_id",
            "formula_cell_id",
            "reference_id",
            "mapping_role",
            name="uq_formula_canonical_mappings_occurrence",
        ),
        CheckConstraint(
            "mapping_role IN ('output', 'input')",
            name="ck_formula_canonical_mappings_role",
        ),
        CheckConstraint(
            "mapping_status IN ('mapped', 'unmapped', 'ambiguous')",
            name="ck_formula_canonical_mappings_status",
        ),
        CheckConstraint(
            "entity_kind IS NULL OR entity_kind IN ('parameter', 'financial_series')",
            name="ck_formula_canonical_mappings_entity_kind",
        ),
        CheckConstraint(
            "(mapping_status = 'mapped' AND entity_kind IS NOT NULL AND entity_id IS NOT NULL) "
            "OR (mapping_status <> 'mapped' AND entity_kind IS NULL AND entity_id IS NULL)",
            name="ck_formula_canonical_mappings_target",
        ),
        Index(
            "ix_formula_canonical_mappings_entity",
            "calculation_rule_extraction_id",
            "entity_kind",
            "entity_id",
        ),
        Index(
            "ix_formula_canonical_mappings_series_value",
            "financial_series_value_id",
        ),
        Index(
            "uq_formula_canonical_mappings_output",
            "calculation_rule_extraction_id",
            "formula_cell_id",
            unique=True,
            sqlite_where=text("mapping_role = 'output'"),
            postgresql_where=text("mapping_role = 'output'"),
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    calculation_rule_extraction_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_rule_extractions.id",
            ondelete="CASCADE",
            name="fk_formula_mappings_extraction",
        ),
        nullable=False,
    )
    formula_cell_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_formula_cells.id",
            ondelete="RESTRICT",
            name="fk_formula_mappings_cell",
        ),
        nullable=False,
    )
    reference_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "formula_references.id",
            ondelete="RESTRICT",
            name="fk_formula_mappings_reference",
        ),
        nullable=True,
    )
    mapping_role = Column(String(16), nullable=False)
    mapping_status = Column(String(16), nullable=False)
    entity_kind = Column(String(32), nullable=True)
    entity_id = Column(Uuid(as_uuid=False), nullable=True)
    financial_series_value_id = Column(Uuid(as_uuid=False), nullable=True)
    warnings_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class FormulaExecutionResultRecord(Base):
    __tablename__ = "formula_execution_results"
    __table_args__ = (
        UniqueConstraint(
            "calculation_rule_extraction_id",
            "formula_cell_id",
            name="uq_formula_results_extraction_cell",
        ),
        CheckConstraint(
            "execution_status IN ('executed', 'not_executable', 'blocked_by_dependency', "
            "'cycle', 'execution_error')",
            name="ck_formula_results_execution_status",
        ),
        CheckConstraint(
            "validation_status IN ('matched', 'mismatched', 'not_comparable', "
            "'no_cached_value', 'execution_error')",
            name="ck_formula_results_validation_status",
        ),
        CheckConstraint(
            "cached_value_freshness IN ('missing', 'unknown', 'recalculation_required')",
            name="ck_formula_results_cache_freshness",
        ),
        Index(
            "ix_formula_results_extraction_status",
            "calculation_rule_extraction_id",
            "execution_status",
        ),
        Index(
            "ix_formula_results_extraction_validation",
            "calculation_rule_extraction_id",
            "validation_status",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    calculation_rule_extraction_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_rule_extractions.id",
            ondelete="CASCADE",
            name="fk_formula_results_extraction",
        ),
        nullable=False,
    )
    formula_cell_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_formula_cells.id",
            ondelete="RESTRICT",
            name="fk_formula_results_cell",
        ),
        nullable=False,
    )
    expression_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "executable_formula_rules.id",
            ondelete="RESTRICT",
            name="fk_formula_results_expression",
        ),
        nullable=False,
    )
    execution_status = Column(String(32), nullable=False)
    calculated_value_type = Column(String(32), nullable=True)
    calculated_value_json = Column(JSON, nullable=True)
    excel_error_code = Column(String(32), nullable=True)
    engine_error_code = Column(String(100), nullable=True)
    direct_input_trace_json = Column(JSON, nullable=True)
    engine_version = Column(String(64), nullable=False)
    semantics_profile = Column(String(64), nullable=False)
    cached_value_type = Column(String(32), nullable=True)
    cached_value_json = Column(JSON, nullable=True)
    absolute_error = Column(Float, nullable=True)
    relative_error = Column(Float, nullable=True)
    validation_status = Column(String(32), nullable=False)
    cached_value_freshness = Column(String(32), nullable=False)
    warnings_json = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
