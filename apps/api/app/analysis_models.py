"""Persistence models for queued analysis and report artifacts."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)

from .database import Base
from .model_extraction_models import utcnow


class MonteCarloRunRecord(Base):
    __tablename__ = "monte_carlo_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', "
            "'cancelled')",
            name="ck_monte_carlo_runs_status",
        ),
        CheckConstraint(
            "trial_count BETWEEN 1 AND 50000",
            name="ck_monte_carlo_runs_trial_count",
        ),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_monte_carlo_runs_request_hash",
        ),
        UniqueConstraint(
            "request_hash",
            name="uq_monte_carlo_runs_request_hash",
        ),
        UniqueConstraint(
            "model_version_id",
            "idempotency_key",
            name="uq_monte_carlo_runs_model_idempotency",
        ),
        Index(
            "ix_monte_carlo_runs_queue",
            "status",
            "created_at",
        ),
        Index(
            "ix_monte_carlo_runs_model_created",
            "model_version_id",
            "created_at",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("model_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    graph_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_graph_versions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    baseline_calculation_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("calculation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_calculation_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("calculation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_hash = Column(CHAR(64), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    trial_count = Column(Integer, nullable=False)
    random_seed = Column(BigInteger, nullable=False)
    method_version = Column(String(64), nullable=False)
    engine_version = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    cancel_requested = Column(Boolean, nullable=False, default=False)
    runtime_ms = Column(Integer, nullable=True)
    worker_id = Column(String(128), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class MonteCarloInputConfigurationRecord(Base):
    __tablename__ = "monte_carlo_input_configurations"
    __table_args__ = (
        UniqueConstraint(
            "monte_carlo_run_id",
            name="uq_monte_carlo_input_configurations_run",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    monte_carlo_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("monte_carlo_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    inputs_json = Column(JSON, nullable=False)
    correlation_matrix_json = Column(JSON, nullable=False)
    selected_output_roles_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class MonteCarloResultArtifactRecord(Base):
    __tablename__ = "monte_carlo_result_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "monte_carlo_run_id",
            name="uq_monte_carlo_result_artifacts_run",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    monte_carlo_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("monte_carlo_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    calibration_json = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=False)
    evidence_hash = Column(CHAR(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CanonicalReportRunRecord(Base):
    __tablename__ = "canonical_report_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_canonical_report_runs_status",
        ),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_canonical_report_runs_request_hash",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_canonical_report_runs_evidence_hash",
        ),
        UniqueConstraint(
            "request_hash",
            name="uq_canonical_report_runs_request_hash",
        ),
        UniqueConstraint(
            "model_version_id",
            "idempotency_key",
            name="uq_canonical_report_runs_model_idempotency",
        ),
        Index(
            "ix_canonical_report_runs_queue",
            "status",
            "created_at",
        ),
        Index(
            "ix_canonical_report_runs_model_created",
            "model_version_id",
            "created_at",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    model_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("model_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    graph_version_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_graph_versions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    calculation_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("calculation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sensitivity_analysis_id = Column(
        Uuid(as_uuid=False),
        ForeignKey(
            "calculation_sensitivity_analyses.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    monte_carlo_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("monte_carlo_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    template_id = Column(String(100), nullable=False)
    template_version = Column(String(64), nullable=False)
    persona_id = Column(String(32), nullable=False)
    persona_json = Column(JSON, nullable=False)
    frozen_evidence_json = Column(JSON, nullable=False)
    evidence_hash = Column(CHAR(64), nullable=False)
    request_hash = Column(CHAR(64), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    runtime_ms = Column(Integer, nullable=True)
    worker_id = Column(String(128), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CanonicalReportArtifactRecord(Base):
    __tablename__ = "canonical_report_artifacts"
    __table_args__ = (
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_canonical_report_artifacts_evidence_hash",
        ),
        UniqueConstraint(
            "report_run_id",
            name="uq_canonical_report_artifacts_run",
        ),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True)
    report_run_id = Column(
        Uuid(as_uuid=False),
        ForeignKey("canonical_report_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_json = Column(JSON, nullable=False)
    evidence_hash = Column(CHAR(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
