"""Durable relational models for canonical Model Extraction output."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import relationship

from .database import Base
from .model_extraction_types import BUSINESS_OUTPUT_ROLES


_BUSINESS_OUTPUT_ROLES_SQL = ", ".join(
    f"'{role}'" for role in BUSINESS_OUTPUT_ROLES
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkbookVersion(Base):
    __tablename__ = "workbook_versions"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_workbook_versions_sha256"),
        UniqueConstraint(
            "storage_type",
            "storage_ref",
            name="uq_workbook_versions_storage_location",
        ),
        CheckConstraint("length(sha256) = 64", name="ck_workbook_versions_sha_length"),
        CheckConstraint("file_size > 0", name="ck_workbook_versions_positive_size"),
        CheckConstraint(
            "storage_type <> 'database' OR content_bytes IS NOT NULL",
            name="ck_workbook_versions_database_has_bytes",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    sha256 = Column(CHAR(64), nullable=False)
    original_filename = Column(String(255), nullable=False)
    storage_type = Column(String(32), nullable=False)
    storage_ref = Column(String(512), nullable=False)
    content_bytes = Column(LargeBinary, nullable=True)
    file_size = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    model_versions = relationship(
        "ModelVersion",
        back_populates="workbook_version",
        passive_deletes=True,
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('extracting', 'extracted', 'materialized', "
            "'extraction_failed', 'persistence_failed')",
            name="ck_model_versions_status",
        ),
        CheckConstraint(
            "validation_status IN ('not_run', 'validated', "
            "'validated_with_warning', 'review_required', 'rejected')",
            name="ck_model_versions_validation_status",
        ),
        Index("ix_model_versions_workbook_created", "workbook_version_id", "created_at"),
        Index("ix_model_versions_status_created", "status", "created_at"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    workbook_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("workbook_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    upload_filename = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False)
    validation_status = Column(String(32), nullable=False)
    submitted = Column(Boolean, nullable=False, default=False)
    stop_reason = Column(String(100), nullable=True)
    extraction_snapshot_json = Column(JSON, nullable=True)
    driver_meta_json = Column(JSON, nullable=True)
    coverage_json = Column(JSON, nullable=True)
    validation_summary_json = Column(JSON, nullable=True)
    time_series_summary_json = Column(JSON, nullable=True)
    validation_results_json = Column(JSON, nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    extracted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    workbook_version = relationship("WorkbookVersion", back_populates="model_versions")
    parameters = relationship(
        "ModelParameter",
        back_populates="model_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    canonical_outputs = relationship(
        "CanonicalOutput",
        back_populates="model_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    financial_series = relationship(
        "FinancialSeries",
        back_populates="model_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ModelParameter(Base):
    __tablename__ = "model_parameters"
    __table_args__ = (
        CheckConstraint("entity_kind = 'parameter'", name="ck_model_parameters_entity_kind"),
        UniqueConstraint(
            "model_version_id",
            "source_sheet",
            "source_cell",
            name="uq_model_parameters_source_cell",
        ),
        Index("ix_model_parameters_model_role", "model_version_id", "validated_role"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_kind = Column(String(32), nullable=False, default="parameter")
    llm_candidate_alias = Column(String(255), nullable=True)
    source_bucket = Column(String(64), nullable=False)
    label = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    canonical_name = Column(String(255), nullable=True)
    submitted_role = Column(String(64), nullable=False)
    validated_role = Column(String(64), nullable=False)
    raw_value_json = Column(JSON, nullable=True)
    validated_value_json = Column(JSON, nullable=True)
    unit = Column(String(100), nullable=True)
    scenario = Column(String(100), nullable=True)
    period_json = Column(JSON, nullable=True)
    source_sheet = Column(String(255), nullable=False)
    source_cell = Column(String(32), nullable=False)
    exact_formula = Column(Text, nullable=True)
    formula_status = Column(String(64), nullable=False)
    source_validation_status = Column(String(32), nullable=False)
    role_validation_status = Column(String(32), nullable=False)
    validation_status = Column(String(32), nullable=False)
    data_type = Column(String(16), nullable=True)
    number_format = Column(Text, nullable=True)
    llm_confidence = Column(Float, nullable=True)
    validation_confidence = Column(Float, nullable=True)
    reasoning_summary = Column(Text, nullable=True)
    validation_warnings_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    model_version = relationship("ModelVersion", back_populates="parameters")


class CanonicalOutput(Base):
    __tablename__ = "canonical_outputs"
    __table_args__ = (
        CheckConstraint(
            "entity_kind = 'canonical_output'",
            name="ck_canonical_outputs_entity_kind",
        ),
        CheckConstraint(
            f"business_role IN ({_BUSINESS_OUTPUT_ROLES_SQL})",
            name="ck_canonical_outputs_business_role",
        ),
        UniqueConstraint(
            "model_version_id",
            "source_sheet",
            "source_cell",
            name="uq_canonical_outputs_source_cell",
        ),
        Index(
            "ix_canonical_outputs_model_role",
            "model_version_id",
            "business_role",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_kind = Column(String(32), nullable=False, default="canonical_output")
    llm_candidate_alias = Column(String(255), nullable=True)
    label = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    canonical_name = Column(String(255), nullable=True)
    business_role = Column(String(64), nullable=False)
    submitted_role = Column(String(64), nullable=False)
    validated_role = Column(String(64), nullable=False)
    raw_value_json = Column(JSON, nullable=True)
    unit = Column(String(100), nullable=True)
    scenario = Column(String(100), nullable=True)
    period_json = Column(JSON, nullable=True)
    source_sheet = Column(String(255), nullable=False)
    source_cell = Column(String(32), nullable=False)
    exact_formula = Column(Text, nullable=True)
    formula_status = Column(String(64), nullable=False)
    source_validation_status = Column(String(32), nullable=False)
    role_validation_status = Column(String(32), nullable=False)
    validation_status = Column(String(32), nullable=False)
    data_type = Column(String(16), nullable=True)
    number_format = Column(Text, nullable=True)
    llm_confidence = Column(Float, nullable=True)
    validation_confidence = Column(Float, nullable=True)
    reasoning_summary = Column(Text, nullable=True)
    validation_warnings_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    model_version = relationship("ModelVersion", back_populates="canonical_outputs")


class FinancialSeries(Base):
    __tablename__ = "financial_series"
    __table_args__ = (
        CheckConstraint(
            "entity_kind = 'financial_series'",
            name="ck_financial_series_entity_kind",
        ),
        CheckConstraint(
            "semantic_role = 'financial_series'",
            name="ck_financial_series_semantic_role",
        ),
        CheckConstraint(
            f"business_role IS NULL OR business_role IN ({_BUSINESS_OUTPUT_ROLES_SQL})",
            name="ck_financial_series_business_role",
        ),
        Index("ix_financial_series_model_id", "model_version_id", "id"),
        Index("ix_financial_series_model_category", "model_version_id", "category"),
        Index(
            "ix_financial_series_model_business_role",
            "model_version_id",
            "business_role",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_kind = Column(String(32), nullable=False, default="financial_series")
    llm_series_alias = Column(String(255), nullable=True)
    label = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    semantic_role = Column(String(64), nullable=False, default="financial_series")
    business_role = Column(String(64), nullable=True)
    unit = Column(String(100), nullable=True)
    frequency = Column(String(64), nullable=True)
    orientation = Column(String(16), nullable=False)
    scenario = Column(String(100), nullable=True)
    entity = Column(String(255), nullable=True)
    currency = Column(String(32), nullable=True)
    calculation_type = Column(String(32), nullable=False)
    period_source_range = Column(Text, nullable=False)
    value_source_range = Column(Text, nullable=False)
    label_source_sheet = Column(String(255), nullable=True)
    label_source_cell = Column(String(32), nullable=True)
    materialization_status = Column(String(32), nullable=False)
    validation_status = Column(String(32), nullable=False)
    aliases_json = Column(JSON, nullable=True)
    formula_pattern_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)
    reasoning_summary = Column(Text, nullable=True)
    llm_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    model_version = relationship("ModelVersion", back_populates="financial_series")
    values = relationship(
        "FinancialSeriesValue",
        back_populates="financial_series",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FinancialSeriesValue.period_index",
    )


class FinancialSeriesValue(Base):
    __tablename__ = "financial_series_values"
    __table_args__ = (
        UniqueConstraint(
            "financial_series_id",
            "period_index",
            name="uq_financial_series_value_period_index",
        ),
        UniqueConstraint(
            "financial_series_id",
            "value_source_sheet",
            "value_source_cell",
            name="uq_financial_series_value_source_cell",
        ),
        CheckConstraint("period_index >= 0", name="ck_financial_series_value_period_index"),
        CheckConstraint(
            "quarter IS NULL OR quarter BETWEEN 1 AND 4",
            name="ck_financial_series_value_quarter",
        ),
        CheckConstraint(
            "month IS NULL OR month BETWEEN 1 AND 12",
            name="ck_financial_series_value_month",
        ),
        Index(
            "ix_financial_series_values_value_source",
            "value_source_sheet",
            "value_source_cell",
            "financial_series_id",
        ),
        Index(
            "ix_financial_series_values_period_source",
            "period_source_sheet",
            "period_source_cell",
            "financial_series_id",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    financial_series_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("financial_series.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_index = Column(Integer, nullable=False)
    raw_period_label_json = Column(JSON, nullable=True)
    display_period_label = Column(Text, nullable=True)
    period_type = Column(String(32), nullable=True)
    year = Column(Integer, nullable=True)
    quarter = Column(Integer, nullable=True)
    month = Column(Integer, nullable=True)
    is_forecast = Column(Boolean, nullable=True)
    value_json = Column(JSON, nullable=True)
    period_source_sheet = Column(String(255), nullable=False)
    period_source_cell = Column(String(32), nullable=False)
    value_source_sheet = Column(String(255), nullable=False)
    value_source_cell = Column(String(32), nullable=False)
    exact_formula = Column(Text, nullable=True)
    formula_status = Column(String(64), nullable=False)
    cached_value_available = Column(Boolean, nullable=False)
    cached_value_freshness = Column(String(32), nullable=True)
    number_format = Column(Text, nullable=True)
    data_type = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    financial_series = relationship("FinancialSeries", back_populates="values")
