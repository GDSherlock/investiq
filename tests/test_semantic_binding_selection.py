from __future__ import annotations

import pytest

from apps.api.app.model_extraction_types import new_uuid
from apps.api.app.semantic_binding_service import (
    build_extracted_semantic_bindings,
)


def _series(
    series_id: str,
    *,
    label: str,
    role: str,
    value_range: str,
) -> dict[str, object]:
    return {
        "id": series_id,
        "label": label,
        "business_role": role,
        "unit": "USDm",
        "frequency": "annual",
        "value_source_range": value_range,
        "validation_status": "validated",
    }


def _point(series_id: str, formula: str) -> dict[str, object]:
    return {
        "financial_series_id": series_id,
        "exact_formula": formula,
    }


def test_best_match_prefers_calculated_revenue_over_direct_reference_alias() -> None:
    model_id = new_uuid()
    alias_id = new_uuid()
    calculated_id = new_uuid()

    bindings = build_extracted_semantic_bindings(
        model_id,
        outputs=[],
        financial_series=[
            _series(
                alias_id,
                label="Revenue",
                role="revenue",
                value_range="P&L!B3:C3",
            ),
            _series(
                calculated_id,
                label="Revenue",
                role="revenue",
                value_range="P&L!B4:C4",
            ),
        ],
        financial_series_values=[
            _point(alias_id, "='Source'!B3"),
            _point(alias_id, "='Source'!C3"),
            _point(calculated_id, "=B8+B9"),
            _point(calculated_id, "=C8+C9"),
        ],
        parameters=[],
    )

    revenue = next(
        binding for binding in bindings if binding["semantic_role"] == "revenue"
    )
    assert revenue["financial_series_id"] == calculated_id
    assert revenue["evidence_json"]["selected_score"] > revenue[
        "evidence_json"
    ]["alternatives"][0]["score"]
    assert "direct_reference_alias_penalty" in revenue["evidence_json"][
        "alternatives"
    ][0]["reasons"]


def test_best_match_uses_labelled_multi_period_minimum_dscr_as_dscr_series() -> None:
    model_id = new_uuid()
    dscr_id = new_uuid()

    bindings = build_extracted_semantic_bindings(
        model_id,
        outputs=[],
        financial_series=[
            _series(
                dscr_id,
                label="DSCR",
                role="minimum_dscr",
                value_range="Debt!B6:C6",
            )
        ],
        financial_series_values=[
            _point(dscr_id, "=B4/B5"),
            _point(dscr_id, "=C4/C5"),
        ],
        parameters=[],
    )

    dscr = next(
        binding for binding in bindings if binding["semantic_role"] == "dscr"
    )
    assert dscr["financial_series_id"] == dscr_id
    assert "compatible_business_role" in dscr["evidence_json"]["reasons"]


def test_project_fcf_compatible_role_prefers_workbook_calculation_over_alias() -> None:
    model_id = new_uuid()
    source_id = new_uuid()
    alias_id = new_uuid()

    bindings = build_extracted_semantic_bindings(
        model_id,
        outputs=[],
        financial_series=[
            _series(
                source_id,
                label="Project free cash flow ($mm)",
                role="cash_flow",
                value_range="'Cash Flow'!B8:C8",
            ),
            _series(
                alias_id,
                label="Project free cash flow ($mm)",
                role="cash_flow",
                value_range="'Returns Calc'!B5:C5",
            ),
        ],
        financial_series_values=[
            _point(source_id, "=B6+B5+B7"),
            _point(source_id, "=C6+C5+C7"),
            _point(alias_id, "='Cash Flow'!B8"),
            _point(alias_id, "='Cash Flow'!C8"),
        ],
        parameters=[],
    )

    binding = next(
        row
        for row in bindings
        if row["semantic_role"] == "project_free_cash_flow"
    )
    assert binding["financial_series_id"] == source_id
    assert "compatible_business_role" in binding["evidence_json"]["reasons"]
    assert "direct_reference_alias_penalty" in binding["evidence_json"][
        "alternatives"
    ][0]["reasons"]


@pytest.mark.parametrize(
    "label",
    [
        "Project free cash flow",
        "Project FCF",
        "Unlevered project cash flow",
        "Project cash flow",
        "Project CF",
    ],
)
def test_project_fcf_accepts_only_controlled_cash_flow_labels(label: str) -> None:
    model_id = new_uuid()
    series_id = new_uuid()

    bindings = build_extracted_semantic_bindings(
        model_id,
        outputs=[],
        financial_series=[
            _series(
                series_id,
                label=label,
                role="cash_flow",
                value_range="Cash Flow!B8:C8",
            )
        ],
        financial_series_values=[
            _point(series_id, "=B5+B6"),
            _point(series_id, "=C5+C6"),
        ],
        parameters=[],
    )

    binding = next(
        row
        for row in bindings
        if row["semantic_role"] == "project_free_cash_flow"
    )
    assert binding["financial_series_id"] == series_id


@pytest.mark.parametrize(
    ("role", "label"),
    [
        ("cash_flow", "Cash flow"),
        ("cash_flow", "Equity cash flow"),
        ("cfads", "CFADS"),
    ],
)
def test_project_fcf_rejects_uncontrolled_labels(role: str, label: str) -> None:
    model_id = new_uuid()
    series_id = new_uuid()

    bindings = build_extracted_semantic_bindings(
        model_id,
        outputs=[],
        financial_series=[
            _series(
                series_id,
                label=label,
                role=role,
                value_range="Cash Flow!B8:C8",
            )
        ],
        financial_series_values=[
            _point(series_id, "=B5+B6"),
            _point(series_id, "=C5+C6"),
        ],
        parameters=[],
    )

    assert all(
        row["semantic_role"] != "project_free_cash_flow" for row in bindings
    )


def test_project_fcf_accepts_misclassified_cfads_with_exact_label() -> None:
    model_id = new_uuid()
    series_id = new_uuid()

    bindings = build_extracted_semantic_bindings(
        model_id,
        outputs=[],
        financial_series=[
            _series(
                series_id,
                label="Project free cash flow ($mm)",
                role="cfads",
                value_range="Cash Flow!B8:C8",
            )
        ],
        financial_series_values=[
            _point(series_id, "=B5+B6"),
            _point(series_id, "=C5+C6"),
        ],
        parameters=[],
    )

    binding = next(
        row
        for row in bindings
        if row["semantic_role"] == "project_free_cash_flow"
    )
    assert binding["financial_series_id"] == series_id
