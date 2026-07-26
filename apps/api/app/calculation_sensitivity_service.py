"""Persisted orchestration for bounded canonical sensitivity cases."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Sequence

from sqlalchemy.orm import Session

from .calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from .calculation_rules.phase2_repository import Phase2CalculationRepository
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
