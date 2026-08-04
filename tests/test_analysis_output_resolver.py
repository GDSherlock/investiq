from __future__ import annotations

from types import SimpleNamespace

from apps.api.app.analysis_output_resolver import (
    resolve_analysis_output,
    resolve_analysis_parameter,
)
from apps.api.app.model_extraction_types import new_uuid
from apps.api.app.schemas import CalculationRunOutputsResponse


def _scalar(role: str, label: str, value: str = "1") -> dict[str, object]:
    projected = {
        "availability_status": "available",
        "value": {"value_type": "number", "value": value},
        "validation_status": "matched",
    }
    return {
        "output_id": new_uuid(),
        "entity_kind": "scalar",
        "business_role": role,
        "label": label,
        "unit": "USDm",
        "mapping_status": "mapped",
        "support_status": "supported",
        "availability_status": "available",
        "baseline": projected,
        "current": projected,
    }


def _projection(outputs: list[dict[str, object]]) -> CalculationRunOutputsResponse:
    run_id = new_uuid()
    return CalculationRunOutputsResponse.model_validate(
        {
            "calculation_run_id": run_id,
            "model_version_id": new_uuid(),
            "graph_version_id": new_uuid(),
            "comparison_baseline_run_id": run_id,
            "outputs": outputs,
        }
    )


def test_npv_perspective_is_resolved_only_by_an_exact_canonical_label() -> None:
    projection = _projection(
        [
            _scalar("npv", "Equity NPV ($mm)", "90"),
            _scalar("npv", "Project NPV ($mm)", "145"),
        ]
    )

    project = resolve_analysis_output(
        projection.outputs,
        "project_npv",
        entity_kind="scalar",
    )
    equity = resolve_analysis_output(
        projection.outputs,
        "equity_npv",
        entity_kind="scalar",
    )

    assert project is not None and project.label == "Project NPV ($mm)"
    assert equity is not None and equity.label == "Equity NPV ($mm)"


def test_legacy_label_resolution_rejects_fuzzy_and_ambiguous_matches() -> None:
    fuzzy = _projection(
        [_scalar("unclassified", "Adjusted Project FCF forecast")]
    )
    ambiguous = _projection(
        [
            _scalar("unclassified", "Project NPV ($mm)"),
            _scalar("unclassified", "Project NPV (USDm)"),
        ]
    )

    assert (
        resolve_analysis_output(
            fuzzy.outputs,
            "project_free_cash_flow",
            entity_kind="scalar",
        )
        is None
    )
    assert (
        resolve_analysis_output(
            ambiguous.outputs,
            "project_npv",
            entity_kind="scalar",
        )
        is None
    )


def test_debt_share_parameter_uses_only_controlled_exact_aliases() -> None:
    debt_share = SimpleNamespace(
        business_role=None,
        label="Debt share",
    )
    assert (
        resolve_analysis_parameter([debt_share], "debt_ratio")
        is debt_share
    )

    for rejected_label in (
        "Debt service",
        "Debt allocation estimate",
    ):
        rejected = SimpleNamespace(
            business_role=None,
            label=rejected_label,
        )
        assert resolve_analysis_parameter([rejected], "debt_ratio") is None


def test_duplicate_debt_share_parameters_are_ambiguous() -> None:
    candidates = [
        SimpleNamespace(business_role=None, label="Debt share"),
        SimpleNamespace(business_role=None, label="Debt share (%)"),
    ]

    assert resolve_analysis_parameter(candidates, "debt_ratio") is None
