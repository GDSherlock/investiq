"""Thin API-facing facade for deterministic calculation integration."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .calculation_rules.phase2_repository import Phase2CalculationRepository
from .calculation_rules.phase2_service import InternalCalculationEngineService
from .calculation_rules.phase2_types import Phase2CalculationConfiguration
from .calculation_rules.repository import CalculationRuleRepository
from .calculation_rules.service import CalculationRuleExtractionService
from .calculation_rules.types import CalculationRuleExtractionConfiguration
from .model_extraction_read_service import ModelExtractionReadService
from .model_extraction_types import (
    ModelVersionNotFound,
    ModelVersionNotReady,
    WorkbookIntegrityError,
)
from .schemas import (
    CalculationBlankValue,
    CalculationBooleanValue,
    CalculationDateValue,
    CalculationErrorDetail,
    CalculationInputItem,
    CalculationInputsResponse,
    CalculationNumberValue,
    CalculationReadinessResponse,
    CalculationReadinessSummary,
    CalculationReadinessVersions,
    CalculationTextValue,
)


class CalculationIntegrationError(RuntimeError):
    """Sanitized domain failure safe to translate at the router boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        resource_id: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.resource_id = resource_id
        super().__init__(message)

    def detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "resource_id": self.resource_id,
        }


class CalculationIntegrationService:
    """The sole adapter between calculation HTTP contracts and engine services."""

    def __init__(
        self,
        session: Session,
        read_service: ModelExtractionReadService,
        *,
        phase1_service: CalculationRuleExtractionService | None = None,
        phase2_service: InternalCalculationEngineService | None = None,
    ) -> None:
        self._session = session
        self._read_service = read_service
        self._phase1_configuration = CalculationRuleExtractionConfiguration()
        self._phase2_configuration = Phase2CalculationConfiguration()
        self._rule_repository = CalculationRuleRepository(session)
        self._phase2_repository = Phase2CalculationRepository(session)
        self._phase1_service = phase1_service or CalculationRuleExtractionService(
            session,
            read_service,
        )
        self._phase2_service = phase2_service or InternalCalculationEngineService(
            session,
            read_service,
        )

    def prepare(self, model_version_id: str) -> CalculationReadinessResponse:
        try:
            model = self._read_service.load_model_version(
                model_version_id,
                require_materialized=True,
            )
            self._phase1_service.extract_and_execute(
                model_version_id=model.id,
                workbook_version_id=model.workbook_version_id,
            )
            self._phase2_service.compile_workbook(
                workbook_version_id=model.workbook_version_id,
            )
            return self.get_readiness(model.id)
        except ModelVersionNotFound as exc:
            raise CalculationIntegrationError(
                "MODEL_VERSION_NOT_FOUND",
                "Model version was not found.",
                status_code=404,
                resource_id=model_version_id,
            ) from exc
        except ModelVersionNotReady as exc:
            raise CalculationIntegrationError(
                "MODEL_NOT_MATERIALIZED",
                "Model version is not canonically materialized.",
                status_code=409,
                resource_id=model_version_id,
            ) from exc
        except WorkbookIntegrityError as exc:
            raise CalculationIntegrationError(
                "WORKBOOK_INTEGRITY_ERROR",
                "Stored workbook integrity verification failed.",
                status_code=500,
                resource_id=model_version_id,
            ) from exc
        except CalculationIntegrationError:
            raise
        except Exception as exc:
            raise CalculationIntegrationError(
                "CALCULATION_PREPARATION_FAILED",
                "Calculation preparation failed.",
                status_code=500,
                resource_id=model_version_id,
            ) from exc

    def get_readiness(self, model_version_id: str) -> CalculationReadinessResponse:
        try:
            model = self._read_service.load_model_version(
                model_version_id,
                require_materialized=False,
            )
            if model.status != "materialized":
                return self._readiness_response(
                    model=model,
                    status="model_not_ready",
                )

            phase1 = self._rule_repository.find_preparation(
                model.id,
                model.workbook_version_id,
                self._phase1_configuration,
            )
            if phase1 is None:
                return self._readiness_response(model=model, status="not_prepared")
            if phase1.status == "running":
                return self._readiness_response(
                    model=model,
                    status="preparing",
                    phase1=phase1,
                )
            if phase1.status == "failed":
                return self._readiness_response(
                    model=model,
                    status="failed",
                    phase1=phase1,
                    error=CalculationErrorDetail(
                        code="CALCULATION_PREPARATION_FAILED",
                        message="Calculation preparation failed.",
                        retryable=False,
                        resource_id=phase1.calculation_rule_extraction_id,
                    ),
                )

            graph = self._phase2_repository.find_matching_graph(
                model.workbook_version_id,
                self._phase2_configuration,
            )
            if graph is None:
                return self._readiness_response(
                    model=model,
                    status="not_prepared",
                    phase1=phase1,
                )
            return self._readiness_response(
                model=model,
                status=(
                    "ready_with_warning"
                    if phase1.status == "completed_with_warning"
                    else "ready"
                ),
                phase1=phase1,
                graph=graph,
            )
        except ModelVersionNotFound as exc:
            raise CalculationIntegrationError(
                "MODEL_VERSION_NOT_FOUND",
                "Model version was not found.",
                status_code=404,
                resource_id=model_version_id,
            ) from exc
        except CalculationIntegrationError:
            raise
        except Exception as exc:
            raise CalculationIntegrationError(
                "CALCULATION_READINESS_UNAVAILABLE",
                "Calculation readiness is unavailable.",
                status_code=500,
                resource_id=model_version_id,
            ) from exc

    def list_inputs(
        self,
        model_version_id: str,
        *,
        target_kind: str = "parameter",
        editable_only: bool = True,
        limit: int = 100,
        cursor: str | None = None,
    ) -> CalculationInputsResponse:
        if target_kind not in {"parameter", "financial_series_value"}:
            raise CalculationIntegrationError(
                "INVALID_INPUT_KIND",
                "Calculation input kind is not supported.",
                status_code=422,
                resource_id=model_version_id,
            )
        if limit < 1 or limit > 500:
            raise CalculationIntegrationError(
                "INVALID_INPUT_KIND",
                "Calculation input limit must be between 1 and 500.",
                status_code=422,
                resource_id=model_version_id,
            )
        readiness = self.get_readiness(model_version_id)
        if readiness.status == "model_not_ready":
            raise CalculationIntegrationError(
                "MODEL_NOT_MATERIALIZED",
                "Model version is not canonically materialized.",
                status_code=409,
                resource_id=model_version_id,
            )
        if readiness.status not in {"ready", "ready_with_warning"}:
            raise CalculationIntegrationError(
                "CALCULATION_NOT_PREPARED",
                "Calculation preparation is not complete.",
                status_code=409,
                resource_id=model_version_id,
            )
        candidates = self._read_service.list_calculation_inputs(
            model_version_id,
            target_kind,
        )
        candidates = [
            candidate
            for candidate in candidates
            if (not editable_only or candidate.editable)
            and (cursor is None or candidate.target_id > cursor)
        ]
        has_more = len(candidates) > limit
        page = candidates[:limit]
        return CalculationInputsResponse(
            model_version_id=model_version_id,
            graph_version_id=readiness.graph_version_id,
            inputs=[self._input_item(candidate) for candidate in page],
            next_cursor=(page[-1].target_id if has_more and page else None),
        )

    @staticmethod
    def _input_item(candidate) -> CalculationInputItem:
        value_type = candidate.value_type
        if value_type == "number":
            current_value = CalculationNumberValue(
                value_type="number",
                value=str(candidate.current_value),
            )
        elif value_type == "boolean":
            current_value = CalculationBooleanValue(
                value_type="boolean",
                value=candidate.current_value,
            )
        elif value_type == "text":
            current_value = CalculationTextValue(
                value_type="text",
                value=candidate.current_value,
            )
        elif value_type == "blank":
            current_value = CalculationBlankValue(value_type="blank", value=None)
        elif value_type == "date":
            current_value = CalculationDateValue(
                value_type="date",
                value=candidate.current_value,
            )
        else:
            raise CalculationIntegrationError(
                "INVALID_OVERRIDE_VALUE",
                "Canonical input has an unsupported value type.",
                status_code=422,
                resource_id=candidate.target_id,
            )
        return CalculationInputItem(
            target_kind=candidate.target_kind,
            target_id=candidate.target_id,
            label=candidate.label,
            category=candidate.category,
            unit=candidate.unit,
            scenario=candidate.scenario,
            period=candidate.period,
            current_value=current_value,
            editable=candidate.editable,
            non_editable_reason=candidate.non_editable_reason,
        )

    def _readiness_response(
        self,
        *,
        model,
        status: str,
        phase1=None,
        graph=None,
        error: CalculationErrorDetail | None = None,
    ) -> CalculationReadinessResponse:
        phase1_summary = phase1.summary if phase1 is not None else {}
        return CalculationReadinessResponse(
            model_version_id=model.id,
            workbook_version_id=model.workbook_version_id,
            model_status=model.status,
            validation_status=model.validation_status,
            status=status,
            calculation_rule_extraction_id=(
                phase1.calculation_rule_extraction_id
                if phase1 is not None
                else None
            ),
            graph_version_id=(graph.graph_version_id if graph is not None else None),
            versions=CalculationReadinessVersions(
                phase1_ir=self._phase1_configuration.ir_version,
                phase2_ir=self._phase2_configuration.ir_version,
                compiler=self._phase2_configuration.compiler_version,
                engine=self._phase2_configuration.engine_version,
                registry=self._phase2_configuration.function_registry_version,
                semantics=self._phase2_configuration.semantics_profile,
            ),
            summary=CalculationReadinessSummary(
                formula_cells_total=int(
                    phase1_summary.get("formula_cells_total", 0)
                ),
                formula_cells_supported=int(
                    phase1_summary.get("formula_cells_executable", 0)
                ),
                graph_nodes=graph.node_count if graph is not None else 0,
                graph_edges=graph.edge_count if graph is not None else 0,
            ),
            warnings=list(phase1.warnings if phase1 is not None else ()),
            error=error,
        )
