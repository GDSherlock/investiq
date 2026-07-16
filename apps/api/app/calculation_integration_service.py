"""Thin API-facing facade for deterministic calculation integration."""

from __future__ import annotations

from decimal import Decimal

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from .calculation_rules.phase2_repository import Phase2CalculationRepository
from .calculation_rules.phase2_service import InternalCalculationEngineService
from .calculation_rules.phase2_types import (
    CalculationOverride,
    Phase2CalculationConfiguration,
)
from .calculation_rules.repository import CalculationRuleRepository
from .calculation_rules.service import CalculationRuleExtractionService
from .calculation_rules.types import CalculationRuleExtractionConfiguration
from .model_extraction_read_service import ModelExtractionReadService
from .model_extraction_types import (
    FinancialSeriesValueNotFound,
    ModelVersionNotFound,
    ModelVersionNotReady,
    ParameterNotFound,
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
    CalculationOutputValue,
    CalculationRequest,
    CalculationReadinessResponse,
    CalculationReadinessSummary,
    CalculationReadinessVersions,
    CalculationRunResponse,
    CalculationRunSummary,
    CalculationRunValueResponse,
    CalculationRunVersions,
    CalculationTextValue,
)


_OUTPUT_VALUE_ADAPTER = TypeAdapter(CalculationOutputValue)


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

    def calculate(
        self,
        model_version_id: str,
        request: CalculationRequest,
    ) -> CalculationRunResponse:
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
        if request.graph_version_id != readiness.graph_version_id:
            raise CalculationIntegrationError(
                "GRAPH_VERSION_MISMATCH",
                "Requested graph version is not current for the model.",
                status_code=409,
                resource_id=request.graph_version_id,
            )
        identities = [override.target.identity for override in request.overrides]
        if len(identities) != len(set(identities)):
            raise CalculationIntegrationError(
                "DUPLICATE_OVERRIDE_TARGET",
                "More than one override targets the same canonical input.",
                status_code=422,
                resource_id=model_version_id,
            )

        try:
            overrides = tuple(
                self._internal_override(model_version_id, override)
                for override in request.overrides
            )
        except (ParameterNotFound, FinancialSeriesValueNotFound) as exc:
            raise CalculationIntegrationError(
                "INVALID_OVERRIDE_TARGET",
                "Override target was not found in the model version.",
                status_code=422,
                resource_id=model_version_id,
            ) from exc

        except CalculationIntegrationError:
            raise
        except (TypeError, ValueError) as exc:
            raise CalculationIntegrationError(
                "INVALID_OVERRIDE_VALUE",
                "Override value is not valid for deterministic calculation.",
                status_code=422,
                resource_id=model_version_id,
            ) from exc

        try:
            result = self._phase2_service.calculate_model(
                model_version_id=model_version_id,
                graph_version_id=request.graph_version_id,
                overrides=overrides,
                idempotency_key=request.idempotency_key,
            )
            graph = self._phase2_repository.load_graph_metadata(
                result.graph_version_id
            )
            if graph is None:
                raise ValueError("Persisted graph metadata was not found")
            return self._run_response(result, graph)
        except CalculationIntegrationError:
            raise
        except Exception as exc:
            raise CalculationIntegrationError(
                "CALCULATION_FAILED",
                "Deterministic calculation failed.",
                status_code=500,
                resource_id=model_version_id,
            ) from exc

    def get_run(self, calculation_run_id: str) -> CalculationRunResponse:
        try:
            bundle = self._phase2_repository.load_run_bundle(calculation_run_id)
            if bundle is None:
                raise CalculationIntegrationError(
                    "CALCULATION_RUN_NOT_FOUND",
                    "Calculation run was not found.",
                    status_code=404,
                    resource_id=calculation_run_id,
                )
            return self._persisted_run_response(bundle.run, bundle.graph)
        except CalculationIntegrationError:
            raise
        except Exception as exc:
            raise CalculationIntegrationError(
                "CALCULATION_RUN_RELOAD_FAILED",
                "Persisted calculation run could not be reloaded.",
                status_code=500,
                resource_id=calculation_run_id,
            ) from exc

    def _internal_override(self, model_version_id: str, override) -> CalculationOverride:
        target = override.target
        if target.kind == "parameter":
            target_id = target.parameter_id
        else:
            target_id = target.financial_series_value_id
        candidate = self._read_service.get_calculation_input(
            model_version_id,
            target.kind,
            target_id,
        )
        if not candidate.editable:
            if candidate.non_editable_reason == "formula_backed":
                raise CalculationIntegrationError(
                    "FORMULA_OVERRIDE_FORBIDDEN",
                    "Formula-backed canonical inputs cannot be overridden.",
                    status_code=422,
                    resource_id=target_id,
                )
            raise CalculationIntegrationError(
                "INVALID_OVERRIDE_TARGET",
                "Canonical input is not editable.",
                status_code=422,
                resource_id=target_id,
            )
        value_type = override.value.value_type
        value = override.value.value
        if value_type == "number":
            value = _normalized_decimal_string(value)
        if target.kind == "parameter":
            return CalculationOverride(
                target_kind="parameter",
                target_id=target_id,
                sheet_name=None,
                cell_address=None,
                value_type=value_type,
                value=value,
            )
        return CalculationOverride(
            target_kind="cell",
            target_id=None,
            sheet_name=candidate.source_sheet,
            cell_address=candidate.source_cell,
            value_type=value_type,
            value=value,
        )

    @staticmethod
    def _run_response(result, graph) -> CalculationRunResponse:
        values = []
        for cell in result.cells:
            value = (
                _OUTPUT_VALUE_ADAPTER.validate_python(cell.value.to_json())
                if cell.value is not None
                else None
            )
            values.append(
                CalculationRunValueResponse(
                    formula_cell_id=cell.formula_cell_id,
                    sheet_name=cell.sheet_name,
                    cell_address=cell.cell_address,
                    status=cell.status,
                    value=value,
                    engine_error_code=cell.engine_error_code,
                    reused_from_run_id=cell.reused_from_run_id,
                    validation_status=cell.validation_status,
                    warnings=list(cell.warnings),
                )
            )
        return CalculationRunResponse(
            calculation_run_id=result.calculation_run_id,
            model_version_id=result.model_version_id,
            graph_version_id=result.graph_version_id,
            base_run_id=result.base_run_id,
            status=result.status,
            versions=CalculationRunVersions(
                phase2_ir=graph.ir_version,
                compiler=graph.compiler_version,
                engine=result.engine_version,
                registry=result.function_registry_version,
                semantics=result.semantics_profile,
            ),
            summary=CalculationRunSummary.model_validate(dict(result.summary)),
            warnings=list(result.warnings),
            values=values,
        )

    @staticmethod
    def _persisted_run_response(run, graph) -> CalculationRunResponse:
        values = []
        for persisted in run.values:
            value = (
                _OUTPUT_VALUE_ADAPTER.validate_python(persisted.value.to_json())
                if persisted.value is not None
                else None
            )
            values.append(
                CalculationRunValueResponse(
                    formula_cell_id=persisted.formula_cell_id,
                    sheet_name=persisted.sheet_name,
                    cell_address=persisted.cell_address,
                    status=persisted.execution_status,
                    value=value,
                    engine_error_code=persisted.engine_error_code,
                    reused_from_run_id=persisted.reused_from_run_id,
                    validation_status=persisted.validation_status,
                    warnings=list(persisted.warnings),
                )
            )
        return CalculationRunResponse(
            calculation_run_id=run.calculation_run_id,
            model_version_id=run.model_version_id,
            graph_version_id=run.graph_version_id,
            base_run_id=run.base_run_id,
            status=run.status,
            versions=CalculationRunVersions(
                phase2_ir=graph.ir_version,
                compiler=graph.compiler_version,
                engine=run.engine_version,
                registry=run.function_registry_version,
                semantics=run.semantics_profile,
            ),
            summary=CalculationRunSummary.model_validate(dict(run.summary)),
            warnings=list(run.warnings),
            values=values,
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


def _normalized_decimal_string(value: str) -> str:
    decimal_value = Decimal(value)
    normalized = format(decimal_value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"", "-0"} else normalized
