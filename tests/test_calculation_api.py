"""Contract tests for the deterministic calculation HTTP API."""

from __future__ import annotations

import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from apps.api.app.schemas import (
    CalculationBlankValue,
    CalculationBooleanValue,
    CalculationDateValue,
    CalculationInputValue,
    CalculationRequest,
)


def _request(*overrides: dict[str, object]) -> dict[str, object]:
    return {
        "graph_version_id": str(uuid.uuid4()),
        "overrides": list(overrides),
        "idempotency_key": None,
    }


def test_number_value_accepts_finite_decimal_string() -> None:
    value = TypeAdapter(CalculationInputValue).validate_python(
        {"value_type": "number", "value": "900.000000000000000001"}
    )

    assert value.value_type == "number"
    assert value.value == "900.000000000000000001"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999999"])
def test_number_value_rejects_non_finite_decimal_string(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {"value_type": "number", "value": value}
        )


def test_formula_like_text_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CalculationInputValue).validate_python(
            {"value_type": "text", "value": "=SUM(A1:A2)"}
        )


def test_blank_date_and_boolean_values_are_accepted() -> None:
    adapter = TypeAdapter(CalculationInputValue)

    assert adapter.validate_python({"value_type": "blank", "value": None}) == (
        CalculationBlankValue(value_type="blank", value=None)
    )
    assert adapter.validate_python(
        {"value_type": "date", "value": "2030-01-01"}
    ) == CalculationDateValue(value_type="date", value="2030-01-01")
    assert adapter.validate_python(
        {"value_type": "boolean", "value": True}
    ) == CalculationBooleanValue(value_type="boolean", value=True)


def test_parameter_and_financial_series_value_targets_are_accepted() -> None:
    parameter_id = str(uuid.uuid4())
    financial_series_value_id = str(uuid.uuid4())

    parameter = CalculationRequest.model_validate(
        _request(
            {
                "target": {"kind": "parameter", "parameter_id": parameter_id},
                "value": {"value_type": "number", "value": "900"},
            }
        )
    )
    financial_value = CalculationRequest.model_validate(
        _request(
            {
                "target": {
                    "kind": "financial_series_value",
                    "financial_series_value_id": financial_series_value_id,
                },
                "value": {"value_type": "number", "value": "125.5"},
            }
        )
    )

    assert parameter.overrides[0].target.parameter_id == parameter_id
    assert (
        financial_value.overrides[0].target.financial_series_value_id
        == financial_series_value_id
    )


def test_raw_cell_target_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CalculationRequest.model_validate(
            _request(
                {
                    "target": {
                        "kind": "cell",
                        "sheet_name": "Inputs",
                        "cell_address": "A1",
                    },
                    "value": {"value_type": "number", "value": "1"},
                }
            )
        )


def test_duplicate_override_target_is_rejected() -> None:
    parameter_id = str(uuid.uuid4())
    override = {
        "target": {"kind": "parameter", "parameter_id": parameter_id},
        "value": {"value_type": "number", "value": "900"},
    }

    with pytest.raises(ValidationError, match="Duplicate override target"):
        CalculationRequest.model_validate(_request(override, override))
