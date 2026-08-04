from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.equity_multiple_derivation import derive_equity_multiple
from apps.api.app.model_extraction_models import ModelSemanticBinding
from apps.api.app.model_extraction_types import new_uuid
from apps.api.app.schemas import (
    CalculationRunScalarOutputItem,
    CalculationRunSeriesOutputItem,
)


def _projected_number(value: str) -> dict[str, object]:
    return {
        "availability_status": "available",
        "value": {"value_type": "number", "value": value},
        "unavailable_reason": None,
        "execution_status": "executed",
        "engine_error_code": None,
        "validation_status": "validated",
        "warnings": [],
    }


def _projected_text(value: str) -> dict[str, object]:
    return {
        "availability_status": "available",
        "value": {"value_type": "text", "value": value},
        "unavailable_reason": None,
        "execution_status": "executed",
        "engine_error_code": None,
        "validation_status": "validated",
        "warnings": [],
    }


def _unavailable_projected() -> dict[str, object]:
    return {
        "availability_status": "unavailable",
        "value": None,
        "unavailable_reason": "blocked_by_dependency",
        "execution_status": "blocked",
        "engine_error_code": None,
        "validation_status": "not_comparable",
        "warnings": [],
    }


def _series(
    output_id: str,
    *,
    baseline: tuple[str, ...],
    current: tuple[str, ...] | None = None,
    current_unavailable_index: int | None = None,
    current_text_index: int | None = None,
    business_role: str = "equity_cash_flow",
) -> CalculationRunSeriesOutputItem:
    current_values = current or baseline
    assert len(baseline) == len(current_values)
    points = []
    for index, (baseline_value, current_value) in enumerate(
        zip(baseline, current_values, strict=True)
    ):
        if index == current_unavailable_index:
            current_projection = _unavailable_projected()
        elif index == current_text_index:
            current_projection = _projected_text(current_value)
        else:
            current_projection = _projected_number(current_value)
        points.append(
            {
                "financial_series_value_id": new_uuid(),
                "period_index": index,
                "period": str(2026 + index),
                "mapping_status": "mapped",
                "support_status": "supported",
                "availability_status": (
                    "partial"
                    if index in {current_unavailable_index, current_text_index}
                    else "available"
                ),
                "baseline": _projected_number(baseline_value),
                "current": current_projection,
            }
        )
    return CalculationRunSeriesOutputItem.model_validate(
        {
            "output_id": output_id,
            "entity_kind": "series",
            "business_role": business_role,
            "label": "Equity cash flow",
            "unit": "USDm",
            "mapping_status": "mapped",
            "support_status": "supported",
            "availability_status": (
                "partial"
                if current_unavailable_index is not None
                or current_text_index is not None
                else "available"
            ),
            "points": points,
        }
    )


def _scalar_equity_multiple(value: str) -> CalculationRunScalarOutputItem:
    return CalculationRunScalarOutputItem.model_validate(
        {
            "output_id": new_uuid(),
            "entity_kind": "scalar",
            "business_role": "equity_multiple",
            "label": "Workbook equity multiple",
            "unit": "x",
            "mapping_status": "mapped",
            "support_status": "supported",
            "availability_status": "available",
            "baseline": _projected_number(value),
            "current": _projected_number(value),
        }
    )


def _reviewed_binding(series_id: str) -> ModelSemanticBinding:
    return ModelSemanticBinding(
        id=new_uuid(),
        model_version_id=new_uuid(),
        semantic_role="equity_cash_flow",
        financial_series_id=series_id,
        binding_source="reviewed",
    )


def test_equity_multiple_sums_all_inflows_over_absolute_outflows() -> None:
    series = _series(
        new_uuid(),
        baseline=("-40", "-60", "0", "25", "50", "75"),
        current=("-50", "-50", "0", "30", "60", "90"),
    )

    derived = derive_equity_multiple([series], binding=None)

    assert derived.baseline.value is not None
    assert derived.current.value is not None
    assert derived.baseline.value.value == "1.5"
    assert derived.current.value.value == "1.8"
    assert derived.availability_status == "available"
    assert derived.source_ids == [series.output_id]
    assert not hasattr(derived, "output_id")


def test_equity_multiple_zero_inflow_is_available_zero() -> None:
    derived = derive_equity_multiple(
        [_series(new_uuid(), baseline=("-100", "0"))],
        binding=None,
    )

    assert derived.current.value is not None
    assert derived.current.value.value == "0"


def test_equity_multiple_zero_outflow_is_typed_unavailable() -> None:
    derived = derive_equity_multiple(
        [_series(new_uuid(), baseline=("10", "20"))],
        binding=None,
    )

    assert derived.current.value is None
    assert derived.current.unavailable_reason == "EQUITY_CASH_OUTFLOW_ZERO"
    assert derived.availability_status == "unavailable"


def test_equity_multiple_rejects_partial_source_without_partial_sum() -> None:
    series = _series(
        new_uuid(),
        baseline=("-100", "120"),
        current=("-100", "120"),
        current_unavailable_index=1,
    )

    derived = derive_equity_multiple([series], binding=None)

    assert derived.baseline.value is not None
    assert derived.baseline.value.value == "1.2"
    assert derived.current.value is None
    assert derived.current.unavailable_reason == "EQUITY_CASH_FLOW_UNAVAILABLE"
    assert derived.availability_status == "partial"


def test_equity_multiple_rejects_text_projected_values() -> None:
    text = derive_equity_multiple(
        [
            _series(
                new_uuid(),
                baseline=("-100", "120"),
                current=("-100", "not-a-number"),
                current_text_index=1,
            )
        ],
        binding=None,
    )

    assert text.current.unavailable_reason == "EQUITY_CASH_FLOW_UNAVAILABLE"


def test_non_finite_projected_numbers_are_rejected_at_the_dto_boundary() -> None:
    with pytest.raises(ValidationError, match="Number value must be finite"):
        _series(new_uuid(), baseline=("-100", "NaN"))


def test_reviewed_binding_wins_over_same_role_candidates() -> None:
    first = _series(new_uuid(), baseline=("-100", "110"))
    reviewed = _series(new_uuid(), baseline=("-100", "150"))

    derived = derive_equity_multiple(
        [first, reviewed],
        binding=_reviewed_binding(reviewed.output_id),
    )

    assert derived.current.value is not None
    assert derived.current.value.value == "1.5"
    assert derived.source_ids == [reviewed.output_id]


def test_missing_bound_series_does_not_fallback_to_another_candidate() -> None:
    candidate = _series(new_uuid(), baseline=("-100", "150"))

    derived = derive_equity_multiple(
        [candidate],
        binding=_reviewed_binding(new_uuid()),
    )

    assert derived.current.value is None
    assert derived.current.unavailable_reason == "EQUITY_CASH_FLOW_NOT_FOUND"
    assert derived.source_ids == []


def test_multiple_unbound_candidates_are_ambiguous() -> None:
    derived = derive_equity_multiple(
        [
            _series(new_uuid(), baseline=("-100", "110")),
            _series(new_uuid(), baseline=("-100", "150")),
        ],
        binding=None,
    )

    assert derived.current.value is None
    assert derived.current.unavailable_reason == "EQUITY_CASH_FLOW_AMBIGUOUS"


def test_workbook_scalar_equity_multiple_is_ignored() -> None:
    cash_flow = _series(new_uuid(), baseline=("-100", "150"))

    derived = derive_equity_multiple(
        [_scalar_equity_multiple("9.9"), cash_flow],
        binding=None,
    )

    assert derived.current.value is not None
    assert derived.current.value.value == "1.5"
    assert derived.source_ids == [cash_flow.output_id]
