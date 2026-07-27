"""Persisted orchestration for bounded canonical sensitivity cases."""

from __future__ import annotations

from decimal import Decimal, localcontext
from time import monotonic
from typing import Sequence
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from .calculation_rules.phase2_repository import Phase2CalculationRepository
from .calculation_rules.phase2_models import CalculationRunRecord
from .calculation_rules.phase2_types import (
    CalculationRunPolicy,
    Phase2CalculationConfiguration,
    canonical_hash,
)
from .schemas import (
    CalculationNumberValue,
    CalculationOverrideRequest,
    CalculationOverrideTarget,
    CalculationProjectedValueItem,
    CalculationRequest,
    CalculationRunOutputsResponse,
    CalculationRunScalarOutputItem,
    CalculationSensitivityCase,
    CalculationSensitivityCaseOutput,
    CalculationSensitivityDriverResult,
    CalculationSensitivityOverrideRequest,
    CalculationSensitivityRequest,
    CalculationSensitivityResponse,
    CalculationSensitivitySelectedOutput,
    CalculationSensitivityTwoWayCell,
    CalculationSensitivityTwoWayResult,
)


_IMPACT_UNAVAILABLE_WARNING = (
    "Impact is unavailable because one or both endpoint outputs are not "
    "available numeric values."
)
_TOP_IMPACT_TWO_WAY_UNAVAILABLE_WARNING = "TOP_IMPACT_TWO_WAY_UNAVAILABLE"


def _target_id(target: CalculationOverrideTarget) -> str:
    if target.kind == "parameter":
        return target.parameter_id
    return target.financial_series_value_id


def _deduplicate_warnings(warnings: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(warnings))


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _calculation_number_literal(value: Decimal) -> str:
    fixed = _decimal_string(value)
    if (
        len(fixed) <= 128
        and len(Decimal(fixed).as_tuple().digits) <= 32
    ):
        return fixed
    return format(value.normalize(), "e")


def _five_linear_values(
    low: CalculationNumberValue,
    high: CalculationNumberValue,
) -> list[CalculationNumberValue]:
    low_value = Decimal(low.value)
    high_value = Decimal(high.value)
    with localcontext() as context:
        context.prec = (
            max(low_value.adjusted(), high_value.adjusted())
            - min(
                int(low_value.as_tuple().exponent),
                int(high_value.as_tuple().exponent),
            )
            + 4
        )
        return [
            CalculationNumberValue(
                value_type="number",
                value=_calculation_number_literal(
                    low_value + (high_value - low_value) * Decimal(index) / 4
                ),
            )
            for index in range(5)
        ]


def _rank_top_impact_drivers(
    drivers: Sequence[CalculationSensitivityDriverResult],
) -> list[CalculationSensitivityDriverResult]:
    ranked = [
        (index, driver)
        for index, driver in enumerate(drivers)
        if driver.impact is not None
    ]
    return [
        driver
        for _index, driver in sorted(
            ranked,
            key=lambda item: (
                -Decimal(item[1].impact or "0"),
                item[0],
                item[1].target.identity,
            ),
        )[:2]
    ]


def _replace_numeric_override(
    current: Sequence[CalculationSensitivityOverrideRequest],
    target: CalculationOverrideTarget,
    value: CalculationNumberValue,
) -> list[CalculationOverrideRequest]:
    merged = {
        override.target.identity: CalculationOverrideRequest(
            target=override.target,
            value=override.value,
        )
        for override in current
    }
    merged[target.identity] = CalculationOverrideRequest(
        target=target,
        value=value,
    )
    return [
        merged[identity]
        for identity in sorted(merged, key=lambda item: (item[0], item[1]))
    ]


def _selected_scalar(
    projection: CalculationRunOutputsResponse,
    output_id: str,
) -> CalculationRunScalarOutputItem:
    selected = next(
        (
            output
            for output in projection.outputs
            if output.output_id == output_id
        ),
        None,
    )
    if selected is None or selected.entity_kind != "scalar":
        raise CalculationIntegrationError(
            "INVALID_SENSITIVITY_OUTPUT",
            "Sensitivity output must be a scalar output in the model.",
            status_code=422,
            resource_id=output_id,
        )
    return selected


class CalculationSensitivityService:
    def __init__(
        self,
        session: Session,
        calculation_service: CalculationIntegrationService,
    ) -> None:
        self._session = session
        self._repository = Phase2CalculationRepository(session)
        self._calculation_service = calculation_service
        self._configuration = Phase2CalculationConfiguration()
        self._policy = CalculationRunPolicy()

    def analyze(
        self,
        model_version_id: str,
        request: CalculationSensitivityRequest,
    ) -> CalculationSensitivityResponse:
        baseline_run_id = self._preflight(model_version_id, request)
        if request.current_run_id is not None:
            started = monotonic()
            try:
                return self._analyze_compact(
                    model_version_id,
                    request,
                    baseline_run_id,
                )
            except CalculationIntegrationError as error:
                self._record_failed_compact_analysis(
                    model_version_id,
                    request,
                    baseline_run_id,
                    error.code,
                    error.message,
                    started,
                )
                raise
            except Exception:
                self._record_failed_compact_analysis(
                    model_version_id,
                    request,
                    baseline_run_id,
                    "SENSITIVITY_BATCH_CALCULATION_FAILED",
                    "Compact sensitivity calculation failed.",
                    started,
                )
                raise
        current_run = self._calculate(
            model_version_id,
            request.graph_version_id,
            self._sorted_current_overrides(request.current_overrides),
        )
        current_projection = self._calculation_service.get_run_outputs(
            current_run.calculation_run_id
        )
        current_output = _selected_scalar(
            current_projection,
            request.output_id,
        )
        self._require_baseline(
            current_projection,
            baseline_run_id,
            model_version_id,
        )

        driver_results = []
        response_warnings = self._output_warnings(current_output.current)
        for driver in request.drivers:
            low_case = self._run_case(
                model_version_id,
                request,
                baseline_run_id,
                driver.target,
                driver.low,
            )
            high_case = self._run_case(
                model_version_id,
                request,
                baseline_run_id,
                driver.target,
                driver.high,
            )
            impact, warnings = self._impact(
                low_case.output,
                high_case.output,
            )
            driver_results.append(
                CalculationSensitivityDriverResult(
                    target=driver.target,
                    low_case=low_case,
                    high_case=high_case,
                    impact=impact,
                    warnings=warnings,
                )
            )
            response_warnings.extend(warnings)

        two_way_result = None
        if request.two_way_mode == "top_impact":
            selected_drivers = _rank_top_impact_drivers(driver_results)
            if len(selected_drivers) < 2:
                response_warnings.append(
                    _TOP_IMPACT_TWO_WAY_UNAVAILABLE_WARNING
                )
            else:
                row_driver, column_driver = selected_drivers
                row_values = _five_linear_values(
                    row_driver.low_case.input_value,
                    row_driver.high_case.input_value,
                )
                column_values = _five_linear_values(
                    column_driver.low_case.input_value,
                    column_driver.high_case.input_value,
                )
                cells = []
                for row_value in row_values:
                    for column_value in column_values:
                        cell = self._run_two_way_cell(
                            model_version_id,
                            request,
                            baseline_run_id,
                            row_driver.target,
                            column_driver.target,
                            row_value,
                            column_value,
                        )
                        cells.append(cell)
                        response_warnings.extend(cell.warnings)
                two_way_result = CalculationSensitivityTwoWayResult(
                    row_target=row_driver.target,
                    column_target=column_driver.target,
                    cells=cells,
                )
        elif request.two_way is not None:
            cells = []
            for row_value in request.two_way.row.values:
                for column_value in request.two_way.column.values:
                    cell = self._run_two_way_cell(
                        model_version_id,
                        request,
                        baseline_run_id,
                        request.two_way.row.target,
                        request.two_way.column.target,
                        row_value,
                        column_value,
                    )
                    cells.append(cell)
                    response_warnings.extend(cell.warnings)
            two_way_result = CalculationSensitivityTwoWayResult(
                row_target=request.two_way.row.target,
                column_target=request.two_way.column.target,
                cells=cells,
            )

        return CalculationSensitivityResponse(
            model_version_id=model_version_id,
            graph_version_id=request.graph_version_id,
            comparison_baseline_run_id=baseline_run_id,
            current_run_id=current_run.calculation_run_id,
            selected_output=CalculationSensitivitySelectedOutput(
                output_id=current_output.output_id,
                business_role=current_output.business_role,
                label=current_output.label,
                unit=current_output.unit,
                scenario=current_output.scenario,
                number_format=current_output.number_format,
                mapping_status=current_output.mapping_status,
                support_status=current_output.support_status,
                availability_status=current_output.availability_status,
                baseline=current_output.baseline,
                current=current_output.current,
            ),
            drivers=driver_results,
            two_way=two_way_result,
            warnings=_deduplicate_warnings(response_warnings),
        )

    def get_analysis(
        self,
        analysis_id: str,
    ) -> CalculationSensitivityResponse:
        row = self._repository.load_sensitivity_analysis(analysis_id)
        if (
            row is None
            or row.status != "completed"
            or row.response_json is None
        ):
            raise CalculationIntegrationError(
                "SENSITIVITY_ANALYSIS_NOT_FOUND",
                "Sensitivity analysis was not found.",
                status_code=404,
                resource_id=analysis_id,
            )
        return CalculationSensitivityResponse.model_validate(
            row.response_json
        )

    def _analyze_compact(
        self,
        model_version_id: str,
        request: CalculationSensitivityRequest,
        baseline_run_id: str,
    ) -> CalculationSensitivityResponse:
        started = monotonic()
        request_payload = {
            "model_version_id": model_version_id,
            **request.model_dump(mode="json"),
        }
        request_hash = canonical_hash(request_payload)
        existing = self._repository.find_completed_sensitivity_analysis(
            request_hash
        )
        if existing is not None and existing.response_json is not None:
            return CalculationSensitivityResponse.model_validate(
                existing.response_json
            )
        analysis_id = str(
            uuid.uuid5(
                uuid.UUID(model_version_id),
                f"calculation-sensitivity|{request_hash}",
            )
        )

        current_projection = self._calculation_service.get_run_outputs(
            request.current_run_id
        )
        self._require_baseline(
            current_projection,
            baseline_run_id,
            model_version_id,
        )
        if (
            current_projection.model_version_id != model_version_id
            or current_projection.graph_version_id
            != request.graph_version_id
        ):
            raise CalculationIntegrationError(
                "SENSITIVITY_CURRENT_RUN_MISMATCH",
                "Current run does not match the requested model or graph.",
                status_code=409,
                resource_id=request.current_run_id,
            )
        current_output = _selected_scalar(
            current_projection,
            request.output_id,
        )
        output_definitions = self._compact_output_definitions(
            model_version_id,
            request.output_id,
            current_projection,
        )
        compact_output_ids = {
            definition.output_id for definition in output_definitions
        }
        current_outputs = [
            CalculationSensitivityCaseOutput(
                output_id=output.output_id,
                business_role=output.business_role,
                label=output.label,
                unit=output.unit,
                scenario=output.scenario,
                number_format=output.number_format,
                value=output.current,
            )
            for output in current_projection.outputs
            if (
                output.entity_kind == "scalar"
                and output.output_id in compact_output_ids
            )
        ]

        endpoint_overrides = []
        endpoint_meta = []
        for driver_index, driver in enumerate(request.drivers):
            for endpoint, input_value in (
                ("low", driver.low),
                ("high", driver.high),
            ):
                endpoint_overrides.append(
                    _replace_numeric_override(
                        request.current_overrides,
                        driver.target,
                        input_value,
                    )
                )
                endpoint_meta.append(
                    (driver_index, endpoint, driver.target, input_value)
                )
        endpoint_values = self._calculation_service.evaluate_sensitivity_cases(
            model_version_id=model_version_id,
            graph_version_id=request.graph_version_id,
            current_run_id=request.current_run_id,
            current_overrides=request.current_overrides,
            case_overrides=endpoint_overrides,
        )

        driver_cases: dict[
            tuple[int, str],
            CalculationSensitivityCase,
        ] = {}
        for meta, values in zip(
            endpoint_meta,
            endpoint_values,
            strict=True,
        ):
            driver_index, endpoint, _target, input_value = meta
            outputs = self._compact_case_outputs(
                output_definitions,
                values,
            )
            selected = self._selected_case_output(
                outputs,
                request.output_id,
            )
            case_id = str(
                uuid.uuid5(
                    uuid.UUID(analysis_id),
                    f"driver|{driver_index}|{endpoint}",
                )
            )
            driver_cases[(driver_index, endpoint)] = (
                CalculationSensitivityCase(
                    case_id=case_id,
                    input_value=input_value,
                    calculation_run_id=None,
                    output=selected,
                    outputs=outputs,
                    warnings=self._output_warnings(selected),
                )
            )

        driver_results = []
        response_warnings = self._output_warnings(current_output.current)
        for driver_index, driver in enumerate(request.drivers):
            low_case = driver_cases[(driver_index, "low")]
            high_case = driver_cases[(driver_index, "high")]
            impact, warnings = self._impact(
                low_case.output,
                high_case.output,
            )
            driver_results.append(
                CalculationSensitivityDriverResult(
                    target=driver.target,
                    low_case=low_case,
                    high_case=high_case,
                    impact=impact,
                    warnings=warnings,
                )
            )
            response_warnings.extend(warnings)

        two_way_spec = None
        if request.two_way_mode == "top_impact":
            selected_drivers = _rank_top_impact_drivers(driver_results)
            if len(selected_drivers) < 2:
                response_warnings.append(
                    _TOP_IMPACT_TWO_WAY_UNAVAILABLE_WARNING
                )
            else:
                two_way_spec = (
                    selected_drivers[0].target,
                    selected_drivers[1].target,
                    _five_linear_values(
                        selected_drivers[0].low_case.input_value,
                        selected_drivers[0].high_case.input_value,
                    ),
                    _five_linear_values(
                        selected_drivers[1].low_case.input_value,
                        selected_drivers[1].high_case.input_value,
                    ),
                )
        elif request.two_way is not None:
            two_way_spec = (
                request.two_way.row.target,
                request.two_way.column.target,
                request.two_way.row.values,
                request.two_way.column.values,
            )

        two_way_result = None
        if two_way_spec is not None:
            row_target, column_target, row_values, column_values = two_way_spec
            matrix_overrides = []
            matrix_meta = []
            for row_index, row_value in enumerate(row_values):
                for column_index, column_value in enumerate(column_values):
                    row_overrides = _replace_numeric_override(
                        request.current_overrides,
                        row_target,
                        row_value,
                    )
                    matrix_overrides.append(
                        _replace_numeric_override(
                            row_overrides,
                            column_target,
                            column_value,
                        )
                    )
                    matrix_meta.append(
                        (
                            row_index,
                            column_index,
                            row_value,
                            column_value,
                        )
                    )
            matrix_values = (
                self._calculation_service.evaluate_sensitivity_cases(
                    model_version_id=model_version_id,
                    graph_version_id=request.graph_version_id,
                    current_run_id=request.current_run_id,
                    current_overrides=request.current_overrides,
                    case_overrides=matrix_overrides,
                )
            )
            cells = []
            for meta, values in zip(
                matrix_meta,
                matrix_values,
                strict=True,
            ):
                row_index, column_index, row_value, column_value = meta
                outputs = self._compact_case_outputs(
                    output_definitions,
                    values,
                )
                selected = self._selected_case_output(
                    outputs,
                    request.output_id,
                )
                cell = CalculationSensitivityTwoWayCell(
                    case_id=str(
                        uuid.uuid5(
                            uuid.UUID(analysis_id),
                            f"matrix|{row_index}|{column_index}",
                        )
                    ),
                    row_value=row_value,
                    column_value=column_value,
                    calculation_run_id=None,
                    output=selected,
                    outputs=outputs,
                    warnings=self._output_warnings(selected),
                )
                cells.append(cell)
                response_warnings.extend(cell.warnings)
            two_way_result = CalculationSensitivityTwoWayResult(
                row_target=row_target,
                column_target=column_target,
                cells=cells,
            )

        case_count = len(endpoint_values) + (
            len(two_way_result.cells) if two_way_result is not None else 0
        )
        response = CalculationSensitivityResponse(
            analysis_id=analysis_id,
            request_hash=request_hash,
            case_count=case_count,
            model_version_id=model_version_id,
            graph_version_id=request.graph_version_id,
            comparison_baseline_run_id=baseline_run_id,
            current_run_id=request.current_run_id,
            selected_output=CalculationSensitivitySelectedOutput(
                output_id=current_output.output_id,
                business_role=current_output.business_role,
                label=current_output.label,
                unit=current_output.unit,
                scenario=current_output.scenario,
                number_format=current_output.number_format,
                mapping_status=current_output.mapping_status,
                support_status=current_output.support_status,
                availability_status=current_output.availability_status,
                baseline=current_output.baseline,
                current=current_output.current,
            ),
            current_outputs=current_outputs,
            drivers=driver_results,
            two_way=two_way_result,
            warnings=_deduplicate_warnings(response_warnings),
        )
        response_payload = response.model_dump(mode="json")
        try:
            self._repository.save_completed_sensitivity_analysis(
                analysis_id=analysis_id,
                model_version_id=model_version_id,
                graph_version_id=request.graph_version_id,
                baseline_run_id=baseline_run_id,
                current_run_id=request.current_run_id,
                configuration=self._configuration,
                request_hash=request_hash,
                request_payload=request_payload,
                response_payload=response_payload,
                case_count=case_count,
                duration_ms=max(0, int((monotonic() - started) * 1000)),
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            completed = (
                self._repository.find_completed_sensitivity_analysis(
                    request_hash
                )
            )
            if completed is None or completed.response_json is None:
                raise
            return CalculationSensitivityResponse.model_validate(
                completed.response_json
            )
        return response

    def _record_failed_compact_analysis(
        self,
        model_version_id: str,
        request: CalculationSensitivityRequest,
        baseline_run_id: str,
        error_code: str,
        error_message: str,
        started: float,
    ) -> None:
        if (
            request.current_run_id is None
            or self._session.get(
                CalculationRunRecord,
                request.current_run_id,
            )
            is None
        ):
            return
        request_payload = {
            "model_version_id": model_version_id,
            **request.model_dump(mode="json"),
        }
        request_hash = canonical_hash(request_payload)
        analysis_id = str(
            uuid.uuid5(
                uuid.UUID(model_version_id),
                f"calculation-sensitivity|{request_hash}",
            )
        )
        try:
            self._repository.save_failed_sensitivity_analysis(
                analysis_id=analysis_id,
                model_version_id=model_version_id,
                graph_version_id=request.graph_version_id,
                baseline_run_id=baseline_run_id,
                current_run_id=request.current_run_id,
                configuration=self._configuration,
                request_hash=request_hash,
                request_payload=request_payload,
                error_code=error_code,
                error_message=error_message,
                duration_ms=max(
                    0,
                    int((monotonic() - started) * 1000),
                ),
            )
            self._session.commit()
        except Exception:
            self._session.rollback()

    def _compact_output_definitions(
        self,
        model_version_id: str,
        selected_output_id: str,
        current_projection: CalculationRunOutputsResponse,
    ):
        definitions = [
            output
            for output in self._calculation_service.list_outputs(
                model_version_id
            ).outputs
            if output.entity_kind == "scalar"
        ]
        current_by_id = {
            output.output_id: output.current
            for output in current_projection.outputs
            if output.entity_kind == "scalar"
        }
        selected = next(
            (
                definition
                for definition in definitions
                if definition.output_id == selected_output_id
            ),
            None,
        )
        slots = (
            ("npv",),
            ("payback_period",),
            ("average_dscr", "minimum_dscr"),
            ("equity_multiple",),
        )
        resolved = [selected] if selected is not None else []
        for roles in slots:
            candidates = [
                definition
                for role in roles
                for definition in definitions
                if definition.business_role == role
            ]
            available = next(
                (
                    definition
                    for definition in candidates
                    if self._is_available_numeric_projection(
                        current_by_id.get(definition.output_id)
                    )
                ),
                None,
            )
            candidate = available or (candidates[0] if candidates else None)
            if (
                candidate is not None
                and all(
                    item.output_id != candidate.output_id
                    for item in resolved
                )
            ):
                resolved.append(candidate)
        return resolved

    @staticmethod
    def _is_available_numeric_projection(
        projected: CalculationProjectedValueItem | None,
    ) -> bool:
        return (
            projected is not None
            and projected.availability_status == "available"
            and isinstance(projected.value, CalculationNumberValue)
        )

    def _compact_case_outputs(
        self,
        definitions,
        values,
    ) -> list[CalculationSensitivityCaseOutput]:
        outputs = []
        for definition in definitions:
            formula_cell_id = (
                definition.source.formula_cell_id
                if definition.source is not None
                else None
            )
            persisted = (
                values.get(formula_cell_id)
                if formula_cell_id is not None
                else None
            )
            projected = self._calculation_service._projected_value(
                persisted,
                missing_reason=(
                    self._calculation_service._missing_projection_reason(
                        definition.mapping_status
                    )
                ),
            )
            outputs.append(
                CalculationSensitivityCaseOutput(
                    output_id=definition.output_id,
                    business_role=definition.business_role,
                    label=definition.label,
                    unit=definition.unit,
                    scenario=definition.scenario,
                    number_format=(
                        definition.source.number_format
                        if definition.source is not None
                        else None
                    ),
                    value=projected,
                )
            )
        return outputs

    @staticmethod
    def _selected_case_output(
        outputs: Sequence[CalculationSensitivityCaseOutput],
        selected_output_id: str,
    ) -> CalculationProjectedValueItem:
        selected = next(
            (
                output
                for output in outputs
                if output.output_id == selected_output_id
            ),
            None,
        )
        if selected is None:
            raise CalculationIntegrationError(
                "INVALID_SENSITIVITY_OUTPUT",
                "Sensitivity output must be a scalar output in the model.",
                status_code=422,
                resource_id=selected_output_id,
            )
        return selected.value

    def _preflight(
        self,
        model_version_id: str,
        request: CalculationSensitivityRequest,
    ) -> str:
        readiness = self._calculation_service.get_readiness(model_version_id)
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

        baseline = self._repository.find_completed_zero_override_run(
            model_version_id,
            request.graph_version_id,
            engine_version=self._configuration.engine_version,
            function_registry_version=(
                self._configuration.function_registry_version
            ),
            semantics_profile=self._configuration.semantics_profile,
            run_policy_hash=canonical_hash(self._policy.to_payload()),
        )
        if baseline is None:
            raise CalculationIntegrationError(
                "CALCULATION_BASELINE_NOT_FOUND",
                "A completed zero-override calculation with matching "
                "versions is required.",
                status_code=409,
                resource_id=model_version_id,
            )

        outputs = self._calculation_service.list_outputs(model_version_id)
        output = next(
            (
                item
                for item in outputs.outputs
                if item.output_id == request.output_id
            ),
            None,
        )
        if output is None or output.entity_kind != "scalar":
            raise CalculationIntegrationError(
                "INVALID_SENSITIVITY_OUTPUT",
                "Sensitivity output must be a scalar output in the model.",
                status_code=422,
                resource_id=request.output_id,
            )

        targets = [
            override.target for override in request.current_overrides
        ] + [driver.target for driver in request.drivers]
        if request.two_way is not None:
            targets.extend(
                [request.two_way.row.target, request.two_way.column.target]
            )
        targets_by_identity = {
            target.identity: target for target in targets
        }
        for target in targets_by_identity.values():
            try:
                candidate = self._calculation_service.get_input(
                    model_version_id,
                    target.kind,
                    _target_id(target),
                )
            except CalculationIntegrationError as error:
                if error.code not in {
                    "INVALID_OVERRIDE_TARGET",
                    "INVALID_OVERRIDE_VALUE",
                }:
                    raise
                raise CalculationIntegrationError(
                    "INVALID_SENSITIVITY_TARGET",
                    "Sensitivity target must be an editable numeric canonical "
                    "input in the model.",
                    status_code=422,
                    resource_id=_target_id(target),
                ) from error
            if (
                not candidate.editable
                or candidate.current_value.value_type != "number"
            ):
                raise CalculationIntegrationError(
                    "INVALID_SENSITIVITY_TARGET",
                    "Sensitivity target must be an editable numeric canonical "
                    "input in the model.",
                    status_code=422,
                    resource_id=_target_id(target),
                )
        if request.two_way_mode == "top_impact":
            for driver in request.drivers:
                try:
                    _five_linear_values(driver.low, driver.high)
                except (ArithmeticError, ValueError) as error:
                    raise CalculationIntegrationError(
                        "INVALID_SENSITIVITY_INTERPOLATION",
                        "Top-impact driver endpoints cannot be interpolated "
                        "exactly within the calculation numeric contract.",
                        status_code=422,
                        resource_id=_target_id(driver.target),
                    ) from error
        return baseline.calculation_run_id

    @staticmethod
    def _sorted_current_overrides(
        current: Sequence[CalculationSensitivityOverrideRequest],
    ) -> list[CalculationOverrideRequest]:
        return [
            CalculationOverrideRequest(
                target=override.target,
                value=override.value,
            )
            for override in sorted(
                current,
                key=lambda item: item.target.identity,
            )
        ]

    def _calculate(
        self,
        model_version_id: str,
        graph_version_id: str,
        overrides: list[CalculationOverrideRequest],
    ):
        return self._calculation_service.calculate(
            model_version_id,
            CalculationRequest(
                graph_version_id=graph_version_id,
                overrides=overrides,
                idempotency_key=None,
            ),
        )

    def _run_case(
        self,
        model_version_id: str,
        request: CalculationSensitivityRequest,
        baseline_run_id: str,
        target: CalculationOverrideTarget,
        input_value: CalculationNumberValue,
    ) -> CalculationSensitivityCase:
        run = self._calculate(
            model_version_id,
            request.graph_version_id,
            _replace_numeric_override(
                request.current_overrides,
                target,
                input_value,
            ),
        )
        projection = self._calculation_service.get_run_outputs(
            run.calculation_run_id
        )
        self._require_baseline(
            projection,
            baseline_run_id,
            model_version_id,
        )
        output = _selected_scalar(projection, request.output_id).current
        return CalculationSensitivityCase(
            input_value=input_value,
            calculation_run_id=run.calculation_run_id,
            output=output,
            warnings=self._output_warnings(output),
        )

    def _run_two_way_cell(
        self,
        model_version_id: str,
        request: CalculationSensitivityRequest,
        baseline_run_id: str,
        row_target: CalculationOverrideTarget,
        column_target: CalculationOverrideTarget,
        row_value: CalculationNumberValue,
        column_value: CalculationNumberValue,
    ) -> CalculationSensitivityTwoWayCell:
        row_overrides = _replace_numeric_override(
            request.current_overrides,
            row_target,
            row_value,
        )
        merged_overrides = _replace_numeric_override(
            row_overrides,
            column_target,
            column_value,
        )
        run = self._calculate(
            model_version_id,
            request.graph_version_id,
            merged_overrides,
        )
        projection = self._calculation_service.get_run_outputs(
            run.calculation_run_id
        )
        self._require_baseline(
            projection,
            baseline_run_id,
            model_version_id,
        )
        output = _selected_scalar(projection, request.output_id).current
        return CalculationSensitivityTwoWayCell(
            row_value=row_value,
            column_value=column_value,
            calculation_run_id=run.calculation_run_id,
            output=output,
            warnings=self._output_warnings(output),
        )

    @staticmethod
    def _output_warnings(output: CalculationProjectedValueItem) -> list[str]:
        warnings = list(output.warnings)
        if output.availability_status != "available":
            reason = output.unavailable_reason or "unknown"
            warnings.append(f"Selected output is unavailable: {reason}.")
        return _deduplicate_warnings(warnings)

    @staticmethod
    def _require_baseline(
        projection: CalculationRunOutputsResponse,
        expected_run_id: str,
        model_version_id: str,
    ) -> None:
        if projection.comparison_baseline_run_id != expected_run_id:
            raise CalculationIntegrationError(
                "CALCULATION_BASELINE_NOT_FOUND",
                "A completed zero-override calculation with matching "
                "versions is required.",
                status_code=409,
                resource_id=model_version_id,
            )

    @staticmethod
    def _impact(
        low: CalculationProjectedValueItem,
        high: CalculationProjectedValueItem,
    ) -> tuple[str | None, list[str]]:
        low_value = low.value
        high_value = high.value
        if (
            low.availability_status != "available"
            or high.availability_status != "available"
            or not isinstance(low_value, CalculationNumberValue)
            or not isinstance(high_value, CalculationNumberValue)
        ):
            return None, [_IMPACT_UNAVAILABLE_WARNING]
        impact = abs(Decimal(high_value.value) - Decimal(low_value.value))
        return _decimal_string(impact), []
