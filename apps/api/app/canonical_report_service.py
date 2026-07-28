"""Canonical report queue and immutable evidence snapshot orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analysis_models import (
    CanonicalReportArtifactRecord,
    CanonicalReportRunRecord,
    MonteCarloRunRecord,
)
from .analysis_presentation_service import AnalysisPresentationService
from .calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from .calculation_rules.phase2_models import (
    CalculationSensitivityAnalysisRecord,
)
from .calculation_rules.phase2_types import canonical_hash
from .canonical_report_generator import generate_canonical_report
from .model_extraction_models import ModelParameter, ModelVersion
from .monte_carlo_service import MonteCarloService
from .schemas import (
    CanonicalReportCreateRequest,
    CanonicalReportHistoryResponse,
    CanonicalReportResponse,
)


_TEMPLATE_ID = "investment-committee-paper"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CanonicalReportService:
    def __init__(
        self,
        session: Session,
        calculation_service: CalculationIntegrationService,
        presentation_service: AnalysisPresentationService,
        monte_carlo_service: MonteCarloService,
    ) -> None:
        self._session = session
        self._calculation_service = calculation_service
        self._presentation_service = presentation_service
        self._monte_carlo_service = monte_carlo_service

    def create_run(
        self,
        model_version_id: str,
        request: CanonicalReportCreateRequest,
    ) -> CanonicalReportResponse:
        snapshot, sensitivity_id, monte_carlo_id = self._freeze_evidence(
            model_version_id,
            request,
        )
        evidence_hash = canonical_hash(snapshot)
        snapshot["evidence_hash"] = evidence_hash
        request_hash = canonical_hash(
            {
                "model_version_id": model_version_id,
                "graph_version_id": request.graph_version_id,
                "calculation_run_id": request.calculation_run_id,
                "sensitivity_analysis_id": sensitivity_id,
                "monte_carlo_run_id": monte_carlo_id,
                "template_version": request.template_version,
                "persona": request.persona.model_dump(mode="json"),
                "evidence_hash": evidence_hash,
            }
        )
        existing = self._session.scalar(
            select(CanonicalReportRunRecord).where(
                CanonicalReportRunRecord.model_version_id
                == model_version_id,
                CanonicalReportRunRecord.idempotency_key
                == request.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise CalculationIntegrationError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency key was already used for a different "
                    "canonical report.",
                    status_code=409,
                    resource_id=existing.id,
                )
            return self.get_run(existing.id)
        equivalent = self._session.scalar(
            select(CanonicalReportRunRecord).where(
                CanonicalReportRunRecord.request_hash == request_hash
            )
        )
        if equivalent is not None:
            return self.get_run(equivalent.id)

        report_id = str(uuid.uuid4())
        run = CanonicalReportRunRecord(
            id=report_id,
            model_version_id=model_version_id,
            graph_version_id=request.graph_version_id,
            calculation_run_id=request.calculation_run_id,
            sensitivity_analysis_id=sensitivity_id,
            monte_carlo_run_id=monte_carlo_id,
            template_id=_TEMPLATE_ID,
            template_version=request.template_version,
            persona_id=request.persona.id,
            persona_json=request.persona.model_dump(mode="json"),
            frozen_evidence_json=snapshot,
            evidence_hash=evidence_hash,
            request_hash=request_hash,
            idempotency_key=request.idempotency_key,
            status="queued",
        )
        self._session.add(run)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            equivalent = self._session.scalar(
                select(CanonicalReportRunRecord).where(
                    CanonicalReportRunRecord.request_hash == request_hash
                )
            )
            if equivalent is None:
                raise
            return self.get_run(equivalent.id)
        return self.get_run(report_id)

    def get_run(self, report_id: str) -> CanonicalReportResponse:
        run = self._session.get(CanonicalReportRunRecord, report_id)
        if run is None:
            raise CalculationIntegrationError(
                "CANONICAL_REPORT_NOT_FOUND",
                "Canonical report was not found.",
                status_code=404,
                resource_id=report_id,
            )
        artifact = self._session.scalar(
            select(CanonicalReportArtifactRecord).where(
                CanonicalReportArtifactRecord.report_run_id == run.id
            )
        )
        return CanonicalReportResponse(
            report_id=run.id,
            model_version_id=run.model_version_id,
            graph_version_id=run.graph_version_id,
            calculation_run_id=run.calculation_run_id,
            sensitivity_analysis_id=run.sensitivity_analysis_id,
            monte_carlo_run_id=run.monte_carlo_run_id,
            template_id=run.template_id,
            template_version=run.template_version,
            persona=run.persona_json,
            evidence_hash=run.evidence_hash,
            status=run.status,
            runtime_ms=run.runtime_ms,
            artifact=artifact.artifact_json if artifact else None,
            error_code=run.error_code,
            error_message=run.error_message,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    def history(
        self,
        model_version_id: str,
        *,
        limit: int = 20,
    ) -> CanonicalReportHistoryResponse:
        if limit < 1 or limit > 100:
            raise CalculationIntegrationError(
                "INVALID_REPORT_HISTORY_LIMIT",
                "Canonical report history limit must be between one and 100.",
                status_code=422,
                resource_id=model_version_id,
            )
        model = self._session.get(ModelVersion, model_version_id)
        if model is None:
            raise CalculationIntegrationError(
                "MODEL_VERSION_NOT_FOUND",
                "Model version was not found.",
                status_code=404,
                resource_id=model_version_id,
            )
        records = list(
            self._session.scalars(
                select(CanonicalReportRunRecord)
                .where(
                    CanonicalReportRunRecord.model_version_id
                    == model_version_id
                )
                .order_by(
                    CanonicalReportRunRecord.created_at.desc(),
                    CanonicalReportRunRecord.id.desc(),
                )
                .limit(limit)
            )
        )
        return CanonicalReportHistoryResponse(
            model_version_id=model_version_id,
            reports=[self.get_run(record.id) for record in records],
        )

    def claim_next(self, worker_id: str) -> str | None:
        query = (
            select(CanonicalReportRunRecord)
            .where(CanonicalReportRunRecord.status == "queued")
            .order_by(
                CanonicalReportRunRecord.created_at,
                CanonicalReportRunRecord.id,
            )
            .limit(1)
        )
        if (
            self._session.bind is not None
            and self._session.bind.dialect.name == "postgresql"
        ):
            query = query.with_for_update(skip_locked=True)
        run = self._session.scalar(query)
        if run is None:
            self._session.rollback()
            return None
        run.status = "running"
        run.worker_id = worker_id
        run.claimed_at = _now()
        run.started_at = run.started_at or _now()
        self._session.commit()
        return run.id

    def requeue_stale(self, timeout_seconds: int = 900) -> int:
        cutoff = _now() - timedelta(seconds=timeout_seconds)
        stale = list(
            self._session.scalars(
                select(CanonicalReportRunRecord).where(
                    CanonicalReportRunRecord.status == "running",
                    CanonicalReportRunRecord.claimed_at < cutoff,
                )
            )
        )
        for run in stale:
            run.status = "queued"
            run.worker_id = None
            run.claimed_at = None
        self._session.commit()
        return len(stale)

    def process_claimed(self, report_id: str) -> None:
        run = self._session.get(CanonicalReportRunRecord, report_id)
        if run is None or run.status != "running":
            return
        started = monotonic()
        try:
            artifact = generate_canonical_report(
                run.frozen_evidence_json
            )
            self._session.add(
                CanonicalReportArtifactRecord(
                    id=str(uuid.uuid4()),
                    report_run_id=run.id,
                    artifact_json=artifact,
                    evidence_hash=run.evidence_hash,
                )
            )
            run.status = "completed"
            run.runtime_ms = int((monotonic() - started) * 1000)
            run.completed_at = _now()
            self._session.commit()
        except Exception as error:
            self._session.rollback()
            run = self._session.get(CanonicalReportRunRecord, report_id)
            if run is not None:
                run.status = "failed"
                run.error_code = "CANONICAL_REPORT_GENERATION_FAILED"
                run.error_message = str(error)
                run.runtime_ms = int((monotonic() - started) * 1000)
                run.completed_at = _now()
                self._session.commit()

    def _freeze_evidence(
        self,
        model_version_id: str,
        request: CanonicalReportCreateRequest,
    ) -> tuple[dict[str, object], str | None, str | None]:
        model = self._session.get(ModelVersion, model_version_id)
        if model is None:
            raise CalculationIntegrationError(
                "MODEL_VERSION_NOT_FOUND",
                "Model version was not found.",
                status_code=404,
                resource_id=model_version_id,
            )
        run = self._calculation_service.get_run(
            request.calculation_run_id
        )
        if (
            run.model_version_id != model_version_id
            or run.graph_version_id != request.graph_version_id
            or run.status
            not in {"completed", "completed_with_warning"}
        ):
            raise CalculationIntegrationError(
                "REPORT_CALCULATION_IDENTITY_MISMATCH",
                "Report calculation must be a completed run from the same "
                "model and graph.",
                status_code=409,
                resource_id=request.calculation_run_id,
            )
        overview = self._presentation_service.overview(
            request.calculation_run_id
        )
        cash_flow = self._presentation_service.cash_flow(
            request.calculation_run_id
        )
        sensitivity = self._select_sensitivity(
            model_version_id,
            request.graph_version_id,
            request.calculation_run_id,
            request.sensitivity_analysis_id,
        )
        monte_carlo = self._select_monte_carlo(
            model_version_id,
            request.graph_version_id,
            request.calculation_run_id,
            request.monte_carlo_run_id,
        )
        assumptions = [
            {
                "parameter_id": parameter.id,
                "business_role": parameter.business_role,
                "label": parameter.label,
                "value": parameter.validated_value_json,
                "unit": parameter.unit,
                "validation_status": parameter.validation_status,
            }
            for parameter in self._session.scalars(
                select(ModelParameter)
                .where(
                    ModelParameter.model_version_id == model_version_id,
                    ModelParameter.business_role.is_not(None),
                )
                .order_by(ModelParameter.business_role, ModelParameter.id)
            )
        ]
        sensitivity_snapshot = (
            {
                "analysis_id": sensitivity.id,
                "request_hash": sensitivity.request_hash,
                "response": sensitivity.response_json,
            }
            if sensitivity is not None
            else None
        )
        monte_snapshot = (
            self._monte_carlo_service.get_run(monte_carlo.id).model_dump(
                mode="json"
            )
            if monte_carlo is not None
            else None
        )
        snapshot: dict[str, object] = {
            "model": {
                "model_version_id": model.id,
                "workbook_version_id": model.workbook_version_id,
                "upload_filename": model.upload_filename,
                "status": model.status,
                "validation_status": model.validation_status,
            },
            "calculation": {
                "calculation_run_id": request.calculation_run_id,
                "run": run.model_dump(mode="json"),
                "overview": overview.model_dump(mode="json"),
                "cash_flow": cash_flow.model_dump(mode="json"),
            },
            "assumptions": assumptions,
            "sensitivity": sensitivity_snapshot,
            "monte_carlo": monte_snapshot,
            "template": {
                "id": _TEMPLATE_ID,
                "version": request.template_version,
            },
            "persona": request.persona.model_dump(mode="json"),
        }
        return (
            snapshot,
            sensitivity.id if sensitivity is not None else None,
            monte_carlo.id if monte_carlo is not None else None,
        )

    def _select_sensitivity(
        self,
        model_version_id: str,
        graph_version_id: str,
        calculation_run_id: str,
        requested_id: str | None,
    ) -> CalculationSensitivityAnalysisRecord | None:
        if requested_id is not None:
            record = self._session.get(
                CalculationSensitivityAnalysisRecord,
                requested_id,
            )
        else:
            record = self._session.scalar(
                select(CalculationSensitivityAnalysisRecord)
                .where(
                    CalculationSensitivityAnalysisRecord.model_version_id
                    == model_version_id,
                    CalculationSensitivityAnalysisRecord.graph_version_id
                    == graph_version_id,
                    CalculationSensitivityAnalysisRecord.current_run_id
                    == calculation_run_id,
                    CalculationSensitivityAnalysisRecord.status
                    == "completed",
                )
                .order_by(
                    CalculationSensitivityAnalysisRecord.created_at.desc(),
                    CalculationSensitivityAnalysisRecord.id.desc(),
                )
                .limit(1)
            )
        if record is None and requested_id is None:
            return None
        if (
            record is None
            or record.model_version_id != model_version_id
            or record.graph_version_id != graph_version_id
            or record.current_run_id != calculation_run_id
            or record.status != "completed"
            or record.response_json is None
        ):
            raise CalculationIntegrationError(
                "REPORT_SENSITIVITY_IDENTITY_MISMATCH",
                "Sensitivity evidence must be a completed artifact from the "
                "same model, graph, and calculation run.",
                status_code=409,
                resource_id=requested_id,
            )
        return record

    def _select_monte_carlo(
        self,
        model_version_id: str,
        graph_version_id: str,
        calculation_run_id: str,
        requested_id: str | None,
    ) -> MonteCarloRunRecord | None:
        if requested_id is not None:
            record = self._session.get(MonteCarloRunRecord, requested_id)
        else:
            record = self._session.scalar(
                select(MonteCarloRunRecord)
                .where(
                    MonteCarloRunRecord.model_version_id
                    == model_version_id,
                    MonteCarloRunRecord.graph_version_id
                    == graph_version_id,
                    MonteCarloRunRecord.current_calculation_run_id
                    == calculation_run_id,
                    MonteCarloRunRecord.status == "completed",
                )
                .order_by(
                    MonteCarloRunRecord.created_at.desc(),
                    MonteCarloRunRecord.id.desc(),
                )
                .limit(1)
            )
        if record is None and requested_id is None:
            return None
        if (
            record is None
            or record.model_version_id != model_version_id
            or record.graph_version_id != graph_version_id
            or record.current_calculation_run_id != calculation_run_id
            or record.status != "completed"
        ):
            raise CalculationIntegrationError(
                "REPORT_MONTE_CARLO_IDENTITY_MISMATCH",
                "Monte Carlo evidence must be a completed artifact from the "
                "same model, graph, and calculation run.",
                status_code=409,
                resource_id=requested_id,
            )
        response = self._monte_carlo_service.get_run(record.id)
        if response.result_artifact is None:
            raise CalculationIntegrationError(
                "REPORT_MONTE_CARLO_ARTIFACT_MISSING",
                "Completed Monte Carlo evidence has no persisted artifact.",
                status_code=409,
                resource_id=record.id,
            )
        return record
