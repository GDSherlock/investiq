"""Run-scoped derived Equity multiple projection."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from .model_extraction_models import ModelSemanticBinding
from .schemas import (
    CalculationDerivedKpiItem,
    CalculationNumberValue,
    CalculationProjectedValueItem,
    CalculationRunOutputItem,
    CalculationRunSeriesOutputItem,
)


_FLOW_UNAVAILABLE = "EQUITY_CASH_FLOW_UNAVAILABLE"
_FLOW_NOT_FOUND = "EQUITY_CASH_FLOW_NOT_FOUND"
_FLOW_AMBIGUOUS = "EQUITY_CASH_FLOW_AMBIGUOUS"
_OUTFLOW_ZERO = "EQUITY_CASH_OUTFLOW_ZERO"


def derive_equity_multiple(
    outputs: Sequence[CalculationRunOutputItem],
    binding: ModelSemanticBinding | None,
) -> CalculationDerivedKpiItem:
    """Derive baseline/current money-on-money from one authoritative flow series."""

    series, selection_error = _select_equity_cash_flow(outputs, binding)
    if series is None:
        assert selection_error is not None
        baseline = _unavailable(selection_error)
        current = _unavailable(selection_error)
        return CalculationDerivedKpiItem(
            role="equity_multiple",
            label="Equity ×",
            unit="x",
            source_type="derived",
            availability_status="unavailable",
            source_ids=[],
            baseline=baseline,
            current=current,
        )

    baseline = _derive_side(series, "baseline")
    current = _derive_side(series, "current")
    statuses = {
        baseline.availability_status,
        current.availability_status,
    }
    availability_status = (
        "available"
        if statuses == {"available"}
        else "unavailable"
        if statuses == {"unavailable"}
        else "partial"
    )
    return CalculationDerivedKpiItem(
        role="equity_multiple",
        label="Equity ×",
        unit="x",
        source_type="derived",
        availability_status=availability_status,
        source_ids=[series.output_id],
        baseline=baseline,
        current=current,
    )


def _select_equity_cash_flow(
    outputs: Sequence[CalculationRunOutputItem],
    binding: ModelSemanticBinding | None,
) -> tuple[CalculationRunSeriesOutputItem | None, str | None]:
    series_outputs = [
        output
        for output in outputs
        if isinstance(output, CalculationRunSeriesOutputItem)
    ]
    if binding is not None:
        bound_id = binding.financial_series_id
        if bound_id is None:
            return None, _FLOW_NOT_FOUND
        bound = [
            item for item in series_outputs if item.output_id == str(bound_id)
        ]
        return (
            (bound[0], None)
            if len(bound) == 1
            else (None, _FLOW_NOT_FOUND)
        )

    candidates = [
        item
        for item in series_outputs
        if item.business_role == "equity_cash_flow"
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, _FLOW_AMBIGUOUS
    return None, _FLOW_NOT_FOUND


def _derive_side(
    series: CalculationRunSeriesOutputItem,
    side: str,
) -> CalculationProjectedValueItem:
    values: list[Decimal] = []
    for point in series.points:
        projected = getattr(point, side)
        if (
            projected.availability_status != "available"
            or projected.value is None
            or projected.value.value_type != "number"
        ):
            return _unavailable(_FLOW_UNAVAILABLE)
        try:
            parsed = Decimal(projected.value.value)
        except (InvalidOperation, ValueError):
            return _unavailable(_FLOW_UNAVAILABLE)
        if not parsed.is_finite():
            return _unavailable(_FLOW_UNAVAILABLE)
        values.append(parsed)

    total_inflow = sum(
        (value for value in values if value > 0),
        Decimal("0"),
    )
    total_outflow = sum(
        (value for value in values if value < 0),
        Decimal("0"),
    )
    outflow_magnitude = abs(total_outflow)
    if outflow_magnitude == 0:
        return _unavailable(_OUTFLOW_ZERO)
    value = _decimal_string(total_inflow / outflow_magnitude)
    return CalculationProjectedValueItem(
        availability_status="available",
        value=CalculationNumberValue(value_type="number", value=value),
        unavailable_reason=None,
        execution_status="derived",
        engine_error_code=None,
        validation_status="derived",
        warnings=[],
    )


def _decimal_string(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"", "-0"} else normalized


def _unavailable(reason: str) -> CalculationProjectedValueItem:
    return CalculationProjectedValueItem(
        availability_status="unavailable",
        value=None,
        unavailable_reason=reason,
        execution_status="derived_unavailable",
        engine_error_code=None,
        validation_status="not_comparable",
        warnings=[],
    )
