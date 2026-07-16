"""Additive SQLAlchemy persistence for the Phase 2 calculation engine."""

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
    UniqueConstraint,
    Uuid,
)

from ..database import Base
from . import models as _phase1_models  # noqa: F401


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkbookNamedExpressionRecord(Base):
    __tablename__ = "workbook_named_expressions"
    __table_args__ = (
        UniqueConstraint(
            "workbook_version_id",
            "scope_type",
            "scope_sheet_name",
            "name",
            name="uq_workbook_named_expressions_scope",
        ),
        CheckConstraint(
            "scope_type IN ('workbook', 'sheet')",
            name="ck_workbook_named_expressions_scope_type",
        ),
        CheckConstraint(
            "target_kind IN ('constant', 'cell', 'range', 'formula', 'unsupported')",
            name="ck_workbook_named_expressions_target_kind",
        ),
        CheckConstraint(
            "resolution_status IN ('resolved', 'unsupported', 'external', 'invalid')",
            name="ck_workbook_named_expressions_resolution",
        ),
        Index(
            "ix_workbook_named_expressions_workbook_name",
            "workbook_version_id",
            "name",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    workbook_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_versions.id",
            ondelete="RESTRICT",
            name="fk_workbook_named_expressions_workbook",
        ),
        nullable=False,
    )
    scope_type = Column(String(16), nullable=False)
    scope_sheet_name = Column(String(255), nullable=True)
    name = Column(String(255), nullable=False)
    definition_text = Column(Text, nullable=False)
    target_kind = Column(String(32), nullable=False)
    resolution_status = Column(String(32), nullable=False)
    resolved_targets_json = Column(JSON, nullable=True)
    definition_sha256 = Column(CHAR(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CalculationGraphVersionRecord(Base):
    __tablename__ = "calculation_graph_versions"
    __table_args__ = (
        UniqueConstraint(
            "workbook_version_id",
            "compiler_manifest_hash",
            name="uq_calculation_graph_versions_manifest",
        ),
        CheckConstraint("node_count >= 0", name="ck_calculation_graph_versions_nodes"),
        CheckConstraint("edge_count >= 0", name="ck_calculation_graph_versions_edges"),
        CheckConstraint(
            "length(compiler_manifest_hash) = 64",
            name="ck_calculation_graph_versions_manifest_hash",
        ),
        CheckConstraint(
            "length(content_fingerprint) = 64",
            name="ck_calculation_graph_versions_fingerprint",
        ),
        Index(
            "ix_calculation_graph_versions_workbook_created",
            "workbook_version_id",
            "created_at",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    workbook_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_versions.id",
            ondelete="RESTRICT",
            name="fk_calculation_graph_versions_workbook",
        ),
        nullable=False,
    )
    compiler_version = Column(String(64), nullable=False)
    ir_version = Column(String(64), nullable=False)
    function_registry_version = Column(String(64), nullable=False)
    semantics_profile = Column(String(64), nullable=False)
    compiler_manifest_hash = Column(CHAR(64), nullable=False)
    content_fingerprint = Column(CHAR(64), nullable=False)
    node_count = Column(Integer, nullable=False)
    edge_count = Column(Integer, nullable=False)
    topological_layers_json = Column(JSON, nullable=False)
    volatile_nodes_json = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CalculationGraphComponentRecord(Base):
    __tablename__ = "calculation_graph_components"
    __table_args__ = (
        UniqueConstraint(
            "graph_version_id",
            "ordinal",
            name="uq_calculation_graph_components_ordinal",
        ),
        CheckConstraint(
            "classification IN ('acyclic_singleton', 'self_reference', "
            "'multi_cell_cycle', 'eligible_iterative_component', 'blocked_unsupported')",
            name="ck_calculation_graph_components_classification",
        ),
        CheckConstraint("member_count > 0", name="ck_calculation_graph_components_members"),
        Index(
            "ix_calculation_graph_components_graph_class",
            "graph_version_id",
            "classification",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    graph_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_graph_versions.id",
            ondelete="CASCADE",
            name="fk_calculation_graph_components_graph",
        ),
        nullable=False,
    )
    ordinal = Column(Integer, nullable=False)
    classification = Column(String(48), nullable=False)
    member_count = Column(Integer, nullable=False)
    member_formula_cells_json = Column(JSON, nullable=False)
    topological_layer = Column(Integer, nullable=True)
    iteration_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class GroupedCalculationRuleRecord(Base):
    __tablename__ = "grouped_calculation_rules"
    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "grouping_profile",
            "group_fingerprint",
            name="uq_grouped_calculation_rules_identity",
        ),
        CheckConstraint(
            "orientation IN ('horizontal', 'vertical')",
            name="ck_grouped_calculation_rules_orientation",
        ),
        CheckConstraint(
            "approval_status IN ('unreviewed', 'approved', 'rejected')",
            name="ck_grouped_calculation_rules_approval",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_grouped_calculation_rules_confidence",
        ),
        CheckConstraint(
            "length(group_fingerprint) = 64",
            name="ck_grouped_calculation_rules_fingerprint",
        ),
        Index(
            "ix_grouped_calculation_rules_model_created",
            "model_version_id",
            "created_at",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "model_versions.id",
            ondelete="RESTRICT",
            name="fk_grouped_calculation_rules_model",
        ),
        nullable=False,
    )
    graph_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_graph_versions.id",
            ondelete="RESTRICT",
            name="fk_grouped_calculation_rules_graph",
        ),
        nullable=False,
    )
    grouping_profile = Column(String(64), nullable=False)
    group_fingerprint = Column(CHAR(64), nullable=False)
    label = Column(Text, nullable=False)
    normalized_expression = Column(Text, nullable=False)
    orientation = Column(String(16), nullable=False)
    exceptions_json = Column(JSON, nullable=False)
    confidence = Column(Float, nullable=False)
    approval_status = Column(String(16), nullable=False)
    compiler_version = Column(String(64), nullable=False)
    semantics_profile = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CalculationRuleMemberRecord(Base):
    __tablename__ = "calculation_rule_members"
    __table_args__ = (
        UniqueConstraint(
            "grouped_rule_id",
            "ordinal",
            name="uq_calculation_rule_members_ordinal",
        ),
        UniqueConstraint(
            "grouped_rule_id",
            "formula_cell_id",
            name="uq_calculation_rule_members_cell",
        ),
        Index("ix_calculation_rule_members_formula", "formula_cell_id"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    grouped_rule_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "grouped_calculation_rules.id",
            ondelete="CASCADE",
            name="fk_calculation_rule_members_group",
        ),
        nullable=False,
    )
    formula_cell_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_formula_cells.id",
            ondelete="RESTRICT",
            name="fk_calculation_rule_members_cell",
        ),
        nullable=False,
    )
    expression_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "executable_formula_rules.id",
            ondelete="RESTRICT",
            name="fk_calculation_rule_members_expression",
        ),
        nullable=False,
    )
    ordinal = Column(Integer, nullable=False)
    period_offset = Column(Integer, nullable=False)
    sheet_name = Column(String(255), nullable=False)
    cell_address = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CalculationRuleDependencyRecord(Base):
    __tablename__ = "calculation_rule_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "grouped_rule_id",
            "dependency_role",
            "dependency_key",
            name="uq_calculation_rule_dependencies_identity",
        ),
        CheckConstraint(
            "dependency_role IN ('input', 'output')",
            name="ck_calculation_rule_dependencies_role",
        ),
        CheckConstraint(
            "canonical_entity_kind IS NULL OR canonical_entity_kind IN ('parameter', 'financial_series')",
            name="ck_calculation_rule_dependencies_entity_kind",
        ),
        Index(
            "ix_calculation_rule_dependencies_canonical",
            "canonical_entity_kind",
            "canonical_entity_id",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    grouped_rule_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "grouped_calculation_rules.id",
            ondelete="CASCADE",
            name="fk_calculation_rule_dependencies_group",
        ),
        nullable=False,
    )
    dependency_role = Column(String(16), nullable=False)
    dependency_key = Column(String(512), nullable=False)
    canonical_entity_kind = Column(String(32), nullable=True)
    canonical_entity_id = Column(Uuid(as_uuid=False), nullable=True)
    source_formula_cell_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_formula_cells.id",
            ondelete="RESTRICT",
            name="fk_calculation_rule_dependencies_cell",
        ),
        nullable=True,
    )
    source_reference_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "formula_references.id",
            ondelete="RESTRICT",
            name="fk_calculation_rule_dependencies_reference",
        ),
        nullable=True,
    )
    evidence_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CalculationRunRecord(Base):
    __tablename__ = "calculation_runs"
    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "graph_version_id",
            "function_registry_version",
            "normalized_override_hash",
            "run_policy_hash",
            name="uq_calculation_runs_identity",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'completed_with_warning', "
            "'failed', 'cancelled')",
            name="ck_calculation_runs_status",
        ),
        CheckConstraint(
            "length(normalized_override_hash) = 64",
            name="ck_calculation_runs_override_hash",
        ),
        CheckConstraint(
            "length(run_policy_hash) = 64",
            name="ck_calculation_runs_policy_hash",
        ),
        Index("ix_calculation_runs_model_created", "model_version_id", "created_at"),
        Index("ix_calculation_runs_graph_status", "graph_version_id", "status"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "model_versions.id",
            ondelete="RESTRICT",
            name="fk_calculation_runs_model",
        ),
        nullable=False,
    )
    graph_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_graph_versions.id",
            ondelete="RESTRICT",
            name="fk_calculation_runs_graph",
        ),
        nullable=False,
    )
    base_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_runs.id",
            ondelete="SET NULL",
            name="fk_calculation_runs_base_run",
        ),
        nullable=True,
    )
    engine_version = Column(String(64), nullable=False)
    function_registry_version = Column(String(64), nullable=False)
    semantics_profile = Column(String(64), nullable=False)
    normalized_override_hash = Column(CHAR(64), nullable=False)
    run_policy_hash = Column(CHAR(64), nullable=False)
    overrides_json = Column(JSON, nullable=False)
    run_policy_json = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False)
    summary_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CalculationRunValueRecord(Base):
    __tablename__ = "calculation_run_values"
    __table_args__ = (
        UniqueConstraint(
            "calculation_run_id",
            "formula_cell_id",
            name="uq_calculation_run_values_cell",
        ),
        CheckConstraint(
            "execution_status IN ('executed', 'not_executable', 'blocked_by_dependency', "
            "'cycle', 'execution_error', 'reused', 'cached_comparison_only', "
            "'iteration_converged', 'iteration_not_converged', 'unavailable')",
            name="ck_calculation_run_values_execution_status",
        ),
        CheckConstraint(
            "validation_status IN ('matched', 'mismatched', 'not_comparable', "
            "'no_cached_value', 'execution_error')",
            name="ck_calculation_run_values_validation_status",
        ),
        Index(
            "ix_calculation_run_values_run_status",
            "calculation_run_id",
            "execution_status",
        ),
        Index("ix_calculation_run_values_formula", "formula_cell_id"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    calculation_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_runs.id",
            ondelete="CASCADE",
            name="fk_calculation_run_values_run",
        ),
        nullable=False,
    )
    formula_cell_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "workbook_formula_cells.id",
            ondelete="RESTRICT",
            name="fk_calculation_run_values_cell",
        ),
        nullable=False,
    )
    expression_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "executable_formula_rules.id",
            ondelete="RESTRICT",
            name="fk_calculation_run_values_expression",
        ),
        nullable=False,
    )
    execution_status = Column(String(32), nullable=False)
    value_type = Column(String(32), nullable=True)
    value_json = Column(JSON, nullable=True)
    excel_error_code = Column(String(32), nullable=True)
    engine_error_code = Column(String(100), nullable=True)
    reused_from_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_runs.id",
            ondelete="SET NULL",
            name="fk_calculation_run_values_reused_run",
        ),
        nullable=True,
    )
    direct_input_trace_json = Column(JSON, nullable=True)
    validation_status = Column(String(32), nullable=False)
    warnings_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
