"""Thin API-facing facade for deterministic calculation integration."""

from __future__ import annotations

from decimal import Decimal
import json
import logging
import traceback

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from .calculation_rules.phase2_repository import Phase2CalculationRepository
from .calculation_rules.phase2_service import InternalCalculationEngineService
from .calculation_rules.phase2_types import (
    CalculationOverride,
    Phase2CalculationConfiguration,
)
from .calculation_rules.repository import CalculationRuleRepository
from .calculation_rules.service import CalculationRuleExtractionService
from .calculation_rules.types import (
    CalculationRuleExtractionConfiguration,
    FormulaIdFactory,
)
from .equity_multiple_derivation import derive_equity_multiple
from .model_extraction_models import ModelSemanticBinding
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
    CalculationOutputDefinitionItem,
    CalculationOutputPointItem,
    CalculationOutputsResponse,
    CalculationOutputSourceItem,
    CalculationOutputValue,
    CalculationRequest,
    CalculationReadinessResponse,
    CalculationReadinessSummary,
    CalculationReadinessVersions,
    CalculationProjectedValueItem,
    CalculationRunOutputsResponse,
    CalculationRunResponse,
    CalculationRunScalarOutputItem,
    CalculationRunSeriesOutputItem,
    CalculationRunSeriesPointItem,
    CalculationRunSummary,
    CalculationRunValueResponse,
    CalculationRunVersions,
    CalculationTextValue,
)


_OUTPUT_VALUE_ADAPTER = TypeAdapter(CalculationOutputValue)
_LOGGER = logging.getLogger("uvicorn.error")


def _sanitized_traceback(exc: BaseException) -> list[dict[str, object]]:
    return [
        {
            "file": frame.filename,
            "function": frame.name,
            "line": frame.lineno,
        }
        for frame in traceback.extract_tb(exc.__traceback__)
    ]


def _log_preparation_failure(
    exc: BaseException,
    *,
    model_version_id: str,
    workbook_version_id: str | None,
    calculation_rule_extraction_id: str | None,
    failure_stage: str,
) -> None:
    payload = {
        "model_version_id": model_version_id,
        "workbook_version_id": workbook_version_id,
        "calculation_rule_extraction_id": calculation_rule_extraction_id,
        "failure_stage": failure_stage,
        "exception_type": type(exc).__name__,
        "traceback": _sanitized_traceback(exc),
    }
    _LOGGER.error(
        "Calculation preparation failed: %s",
        json.dumps(payload, sort_keys=True),
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
        workbook_version_id: str | None = None
        calculation_rule_extraction_id: str | None = None
        failure_stage = "model_lookup"
        try:
            model = self._read_service.load_model_version(
                model_version_id,
                require_materialized=True,
            )
            workbook_version_id = model.workbook_version_id
            calculation_rule_extraction_id = FormulaIdFactory.extraction_id(
                model.id,
                workbook_version_id,
                self._phase1_configuration,
            )
            failure_stage = "phase1_preparation"
            self._phase1_service.extract_and_execute(
                model_version_id=model.id,
                workbook_version_id=workbook_version_id,
            )
            failure_stage = "phase2_compilation"
            self._phase2_service.compile_workbook(
                workbook_version_id=workbook_version_id,
            )
            failure_stage = "readiness_reload"
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
            _log_preparation_failure(
                exc,
                model_version_id=model_version_id,
                workbook_version_id=workbook_version_id,
                calculation_rule_extraction_id=calculation_rule_extraction_id,
                failure_stage=failure_stage,
            )
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

    def get_input(
        self,
        model_version_id: str,
        target_kind: str,
        target_id: str,
    ) -> CalculationInputItem:
        if target_kind not in {"parameter", "financial_series_value"}:
            raise CalculationIntegrationError(
                "INVALID_INPUT_KIND",
                "Calculation input kind is not supported.",
                status_code=422,
                resource_id=target_id,
            )
        try:
            candidate = self._read_service.get_calculation_input(
                model_version_id,
                target_kind,
                target_id,
            )
            return self._input_item(candidate)
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
        except (ParameterNotFound, FinancialSeriesValueNotFound) as exc:
            raise CalculationIntegrationError(
                "INVALID_OVERRIDE_TARGET",
                "Override target was not found in the model version.",
                status_code=422,
                resource_id=target_id,
            ) from exc
        except CalculationIntegrationError:
            raise
        except (TypeError, ValueError) as exc:
            raise CalculationIntegrationError(
                "INVALID_OVERRIDE_VALUE",
                "Canonical input has an unsupported value type.",
                status_code=422,
                resource_id=target_id,
            ) from exc

    def list_outputs(self, model_version_id: str) -> CalculationOutputsResponse:
        try:
            definitions = self._read_service.list_calculation_outputs(
                model_version_id
            )
            return CalculationOutputsResponse(
                model_version_id=model_version_id,
                outputs=[
                    CalculationOutputDefinitionItem(
                        output_id=definition.output_id,
                        entity_kind=definition.entity_kind,
                        business_role=definition.business_role,
                        label=definition.label,
                        unit=definition.unit,
                        scenario=definition.scenario,
                        mapping_status=definition.mapping_status,
                        support_status=definition.support_status,
                        source=(
                            CalculationOutputSourceItem(
                                sheet_name=definition.source.sheet_name,
                                cell_address=definition.source.cell_address,
                                formula_cell_id=definition.source.formula_cell_id,
                                formula_status=definition.source.formula_status,
                                number_format=definition.source.number_format,
                            )
                            if definition.source is not None
                            else None
                        ),
                        points=[
                            CalculationOutputPointItem(
                                financial_series_value_id=point.financial_series_value_id,
                                period_index=point.period_index,
                                period=point.period,
                                formula_cell_id=point.formula_cell_id,
                                mapping_status=point.mapping_status,
                                support_status=point.support_status,
                                source_sheet=point.source_sheet,
                                source_cell=point.source_cell,
                                formula_status=point.formula_status,
                                number_format=point.number_format,
                            )
                            for point in definition.points
                        ],
                    )
                    for definition in definitions
                ],
            )
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
        except CalculationIntegrationError:
            raise
        except Exception as exc:
            raise CalculationIntegrationError(
                "CALCULATION_OUTPUT_DISCOVERY_UNAVAILABLE",
                "Calculation output discovery is unavailable.",
                status_code=500,
                resource_id=model_version_id,
            ) from exc

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

    def get_run_outputs(
        self,
        calculation_run_id: str,
    ) -> CalculationRunOutputsResponse:
        try:
            bundle = self._phase2_repository.load_run_bundle(calculation_run_id)
            if bundle is None:
                raise CalculationIntegrationError(
                    "CALCULATION_RUN_NOT_FOUND",
                    "Calculation run was not found.",
                    status_code=404,
                    resource_id=calculation_run_id,
                )
            current_run = bundle.run
            baseline_run = (
                self._phase2_repository.find_completed_zero_override_run(
                    current_run.model_version_id,
                    current_run.graph_version_id,
                    engine_version=current_run.engine_version,
                    function_registry_version=(
                        current_run.function_registry_version
                    ),
                    semantics_profile=current_run.semantics_profile,
                    run_policy_hash=current_run.run_policy_hash,
                )
                )
            if baseline_run is None:
                raise CalculationIntegrationError(
                    "CALCULATION_BASELINE_NOT_FOUND",
                    "A completed zero-override calculation with matching "
                    "versions is required.",
                    status_code=409,
                    resource_id=current_run.model_version_id,
                )
            definitions = self._read_service.list_calculation_outputs(
                current_run.model_version_id
            )
            baseline_values = {
                value.formula_cell_id: value for value in baseline_run.values
            }
            current_values = {
                value.formula_cell_id: value for value in current_run.values
            }
            outputs = []
            for definition in definitions:
                if definition.entity_kind == "scalar":
                    formula_cell_id = (
                        definition.source.formula_cell_id
                        if definition.source is not None
                        else None
                    )
                    baseline_persisted = (
                        baseline_values.get(formula_cell_id)
                        if formula_cell_id is not None
                        else None
                    )
                    current_persisted = (
                        current_values.get(formula_cell_id)
                        if formula_cell_id is not None
                        else None
                    )
                    baseline = self._projected_value(
                        baseline_persisted,
                        missing_reason=self._missing_projection_reason(
                            definition.mapping_status
                        ),
                    )
                    current = self._projected_value(
                        current_persisted,
                        missing_reason=self._missing_projection_reason(
                            definition.mapping_status
                        ),
                    )
                    outputs.append(
                        CalculationRunScalarOutputItem(
                            output_id=definition.output_id,
                            entity_kind="scalar",
                            business_role=definition.business_role,
                            label=definition.label,
                            unit=definition.unit,
                            scenario=definition.scenario,
                            formula_cell_id=formula_cell_id,
                            mapping_status=definition.mapping_status,
                            support_status=(
                                current_persisted.support_status
                                if current_persisted is not None
                                else definition.support_status
                            ),
                            number_format=(
                                definition.source.number_format
                                if definition.source is not None
                                else None
                            ),
                            availability_status=self._availability_status(
                                baseline,
                                current,
                            ),
                            baseline=baseline,
                            current=current,
                        )
                    )
                    continue

                points = []
                for point in definition.points:
                    baseline_persisted = (
                        baseline_values.get(point.formula_cell_id)
                        if point.formula_cell_id is not None
                        else None
                    )
                    current_persisted = (
                        current_values.get(point.formula_cell_id)
                        if point.formula_cell_id is not None
                        else None
                    )
                    baseline = self._projected_value(
                        baseline_persisted,
                        missing_reason=self._missing_projection_reason(
                            point.mapping_status
                        ),
                    )
                    current = self._projected_value(
                        current_persisted,
                        missing_reason=self._missing_projection_reason(
                            point.mapping_status
                        ),
                    )
                    points.append(
                        CalculationRunSeriesPointItem(
                            financial_series_value_id=(
                                point.financial_series_value_id
                            ),
                            period_index=point.period_index,
                            period=point.period,
                            formula_cell_id=point.formula_cell_id,
                            mapping_status=point.mapping_status,
                            support_status=(
                                current_persisted.support_status
                                if current_persisted is not None
                                else point.support_status
                            ),
                            number_format=point.number_format,
                            availability_status=self._availability_status(
                                baseline,
                                current,
                            ),
                            baseline=baseline,
                            current=current,
                        )
                    )
                outputs.append(
                    CalculationRunSeriesOutputItem(
                        output_id=definition.output_id,
                        entity_kind="series",
                        business_role=definition.business_role,
                        label=definition.label,
                        unit=definition.unit,
                        scenario=definition.scenario,
                        mapping_status=definition.mapping_status,
                        support_status=self._aggregate_support_status(
                            [point.support_status for point in points],
                            fallback=definition.support_status,
                        ),
                        availability_status=self._aggregate_availability_status(
                            [point.availability_status for point in points]
                        ),
                        points=points,
                    )
                )
            binding = self._session.scalar(
                select(ModelSemanticBinding).where(
                    ModelSemanticBinding.model_version_id
                    == current_run.model_version_id,
                    ModelSemanticBinding.semantic_role == "equity_cash_flow",
                )
            )
            derived_equity_multiple = derive_equity_multiple(outputs, binding)
            return CalculationRunOutputsResponse(
                calculation_run_id=current_run.calculation_run_id,
                model_version_id=current_run.model_version_id,
                graph_version_id=current_run.graph_version_id,
                base_run_id=current_run.base_run_id,
                comparison_baseline_run_id=baseline_run.calculation_run_id,
                outputs=outputs,
                derived_kpis=[derived_equity_multiple],
            )
        except CalculationIntegrationError:
            raise
        except Exception as exc:
            raise CalculationIntegrationError(
                "CALCULATION_RUN_OUTPUT_PROJECTION_FAILED",
                "Persisted calculation outputs could not be projected.",
                status_code=500,
                resource_id=calculation_run_id,
            ) from exc

    def evaluate_sensitivity_cases(
        self,
        *,
        model_version_id: str,
        graph_version_id: str,
        current_run_id: str,
        current_overrides,
        case_overrides,
    ):
        """Evaluate compact sensitivity cases without persisting run rows."""
        try:
            return self._phase2_service.evaluate_sensitivity_cases(
                model_version_id=model_version_id,
                graph_version_id=graph_version_id,
                current_run_id=current_run_id,
                current_overrides=[
                    self._internal_override(model_version_id, override)
                    for override in current_overrides
                ],
                case_overrides=[
                    [
                        self._internal_override(model_version_id, override)
                        for override in overrides
                    ]
                    for overrides in case_overrides
                ],
            )
        except CalculationIntegrationError:
            raise
        except ValueError as exc:
            raise CalculationIntegrationError(
                "SENSITIVITY_CURRENT_RUN_MISMATCH",
                "Current run does not match the model, graph, or normalized "
                "sensitivity overrides.",
                status_code=409,
                resource_id=current_run_id,
            ) from exc
        except Exception as exc:
            raise CalculationIntegrationError(
                "SENSITIVITY_BATCH_CALCULATION_FAILED",
                "Compact sensitivity calculation failed.",
                status_code=500,
                resource_id=model_version_id,
            ) from exc

    @staticmethod
    def _projected_value(
        persisted,
        *,
        missing_reason: str,
    ) -> CalculationProjectedValueItem:
        execution_status = (
            persisted.execution_status if persisted is not None else None
        )
        is_available = (
            persisted is not None
            and execution_status in {"executed", "reused"}
            and persisted.value is not None
        )
        value = (
            _OUTPUT_VALUE_ADAPTER.validate_python(persisted.value.to_json())
            if is_available
            else None
        )
        return CalculationProjectedValueItem(
            availability_status="available" if is_available else "unavailable",
            value=value,
            unavailable_reason=(
                None
                if is_available
                else execution_status or missing_reason
            ),
            execution_status=execution_status,
            engine_error_code=(
                persisted.engine_error_code if persisted is not None else None
            ),
            validation_status=(
                persisted.validation_status if persisted is not None else None
            ),
            warnings=list(persisted.warnings) if persisted is not None else [],
        )

    @staticmethod
    def _missing_projection_reason(mapping_status: str) -> str:
        if mapping_status == "static":
            return "static_not_calculation_addressable"
        if mapping_status == "missing":
            return "formula_cell_missing"
        return "run_value_missing"

    @staticmethod
    def _availability_status(
        baseline: CalculationProjectedValueItem,
        current: CalculationProjectedValueItem,
    ) -> str:
        statuses = {
            baseline.availability_status,
            current.availability_status,
        }
        if statuses == {"available"}:
            return "available"
        if statuses == {"unavailable"}:
            return "unavailable"
        return "partial"

    @staticmethod
    def _aggregate_availability_status(statuses: list[str]) -> str:
        if not statuses:
            return "unavailable"
        unique_statuses = set(statuses)
        if unique_statuses == {"available"}:
            return "available"
        if unique_statuses == {"unavailable"}:
            return "unavailable"
        return "partial"

    @staticmethod
    def _aggregate_support_status(
        statuses: list[str],
        *,
        fallback: str,
    ) -> str:
        if not statuses:
            return fallback
        unique_statuses = set(statuses)
        if len(unique_statuses) == 1:
            return next(iter(unique_statuses))
        return "partial"

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
