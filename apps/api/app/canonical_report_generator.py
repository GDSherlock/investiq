"""Deterministic IC report rendering from a frozen canonical evidence bundle."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


CANONICAL_IC_SECTION_KEYS = (
    "executive_recommendation",
    "project_transaction_overview",
    "key_investment_assumptions",
    "construction_completion_risk",
    "operating_revenue_profile",
    "financial_returns",
    "funding_capital_structure",
    "debt_service_covenant_analysis",
    "sensitivity_analysis",
    "monte_carlo_results",
    "key_risks_mitigants",
    "approval_conditions",
    "final_recommendation",
)

_SECTION_TITLES = {
    "executive_recommendation": "Executive recommendation",
    "project_transaction_overview": "Project and transaction overview",
    "key_investment_assumptions": "Key investment assumptions",
    "construction_completion_risk": "Construction and completion risk",
    "operating_revenue_profile": "Operating and revenue profile",
    "financial_returns": "Financial returns",
    "funding_capital_structure": "Funding and capital structure",
    "debt_service_covenant_analysis": (
        "Debt service and covenant analysis"
    ),
    "sensitivity_analysis": "Sensitivity analysis",
    "monte_carlo_results": "Monte Carlo results",
    "key_risks_mitigants": "Key risks and mitigants",
    "approval_conditions": "Approval conditions",
    "final_recommendation": "Final recommendation",
}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return (
        value
        if isinstance(value, Sequence) and not isinstance(value, str)
        else []
    )


def _source_ids(items: Sequence[object], *extra: object) -> list[str]:
    result: list[str] = []
    for item in [*items, *extra]:
        if isinstance(item, str) and item not in result:
            result.append(item)
        elif isinstance(item, Mapping):
            for source_id in _sequence(item.get("source_ids")):
                if isinstance(source_id, str) and source_id not in result:
                    result.append(source_id)
    return result


def _section(
    key: str,
    availability_status: str,
    body: str,
    source_ids: Sequence[str],
) -> dict[str, object]:
    return {
        "ordinal": CANONICAL_IC_SECTION_KEYS.index(key) + 1,
        "key": key,
        "title": _SECTION_TITLES[key],
        "availability_status": availability_status,
        "body": body,
        "source_ids": list(dict.fromkeys(source_ids)),
    }


def _chart(
    snapshot: Mapping[str, Any],
    slot: str,
) -> Mapping[str, Any]:
    calculation = _mapping(snapshot.get("calculation"))
    overview = _mapping(calculation.get("overview"))
    cash_flow = _mapping(calculation.get("cash_flow"))
    for candidate in [
        *_sequence(overview.get("charts")),
        *_sequence(cash_flow.get("charts")),
    ]:
        if isinstance(candidate, Mapping) and candidate.get("slot") == slot:
            return candidate
    return {}


def _chart_summary(chart: Mapping[str, Any]) -> tuple[str, list[str]]:
    available_series = [
        series
        for series in _sequence(chart.get("series"))
        if isinstance(series, Mapping)
        and series.get("availability_status") == "available"
    ]
    if not available_series:
        return "", []
    descriptions: list[str] = []
    sources: list[str] = []
    for series in available_series:
        points = [
            point
            for point in _sequence(series.get("points"))
            if isinstance(point, Mapping) and point.get("value") is not None
        ]
        descriptions.append(
            f"{series.get('label', series.get('role', 'Series'))}: "
            f"{len(points)} available period(s)"
        )
        sources.extend(_source_ids([series]))
        for point in points:
            source_id = point.get("source_id")
            if isinstance(source_id, str):
                sources.append(source_id)
    return "; ".join(descriptions), list(dict.fromkeys(sources))


def _available_kpis(
    snapshot: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    calculation = _mapping(snapshot.get("calculation"))
    overview = _mapping(calculation.get("overview"))
    return [
        item
        for item in _sequence(overview.get("kpis"))
        if isinstance(item, Mapping)
        and item.get("availability_status") == "available"
        and item.get("value") is not None
    ]


def _kpi_summary(kpis: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(
        f"{item.get('label', item.get('role', 'Metric'))}: "
        f"{item.get('display_value', item.get('value'))}"
        for item in kpis
    )


def _sensitivity_summary(
    sensitivity: Mapping[str, Any],
) -> tuple[str, list[str]]:
    response = _mapping(sensitivity.get("response"))
    analysis_id = sensitivity.get("analysis_id")
    if not response or not isinstance(analysis_id, str):
        return "", []
    selected = _mapping(response.get("selected_output"))
    label = selected.get("label") or selected.get("business_role") or "output"
    case_count = response.get("case_count", 0)
    driver_count = len(_sequence(response.get("drivers")))
    return (
        f"Persisted sensitivity analysis covers {case_count} case(s) "
        f"across {driver_count} driver(s) for {label}.",
        [analysis_id],
    )


def _monte_carlo_summary(
    monte_carlo: Mapping[str, Any],
) -> tuple[str, list[str], list[str]]:
    run_id = monte_carlo.get("monte_carlo_run_id")
    artifact = _mapping(monte_carlo.get("result_artifact"))
    if not artifact or not isinstance(run_id, str):
        return "", [], []
    summaries: list[str] = []
    risks: list[str] = []
    for metric in _sequence(artifact.get("metrics")):
        if (
            not isinstance(metric, Mapping)
            or metric.get("availability_status") != "available"
        ):
            continue
        percentiles = _mapping(metric.get("percentiles"))
        if percentiles:
            summaries.append(
                f"{metric.get('label', metric.get('role', 'Metric'))}: "
                f"P10 {percentiles.get('p10')}, "
                f"P50 {percentiles.get('p50')}, "
                f"P90 {percentiles.get('p90')}"
            )
        probabilities = _mapping(metric.get("probabilities"))
        for key, value in probabilities.items():
            risks.append(
                f"{metric.get('label', metric.get('role', 'Metric'))} "
                f"{str(key).replace('_', ' ')}: {value}"
            )
    return "; ".join(summaries), [run_id], risks


def generate_canonical_report(
    snapshot: Mapping[str, Any],
) -> dict[str, object]:
    calculation = _mapping(snapshot.get("calculation"))
    calculation_run_id = calculation.get("calculation_run_id")
    calculation_sources = (
        [calculation_run_id] if isinstance(calculation_run_id, str) else []
    )
    kpis = _available_kpis(snapshot)
    kpi_sources = _source_ids(kpis, *calculation_sources)
    return_summary = _kpi_summary(kpis)

    assumptions = [
        item
        for item in _sequence(snapshot.get("assumptions"))
        if isinstance(item, Mapping)
    ]
    assumption_body = "; ".join(
        f"{item.get('label', item.get('business_role', 'Assumption'))}: "
        f"{item.get('value')} {item.get('unit') or ''}".strip()
        for item in assumptions[:12]
    )
    assumption_sources = [
        str(item["parameter_id"])
        for item in assumptions
        if isinstance(item.get("parameter_id"), str)
    ]

    capex_summary, capex_sources = _chart_summary(
        _chart(snapshot, "capex_construction_profile")
    )
    operating_summary, operating_sources = _chart_summary(
        _chart(snapshot, "operating_trajectory")
    )
    capital_summary, capital_sources = _chart_summary(
        _chart(snapshot, "capital_structure")
    )
    debt_summary, debt_sources = _chart_summary(
        _chart(snapshot, "debt_coverage")
    )
    if not debt_summary:
        debt_summary, debt_sources = _chart_summary(
            _chart(snapshot, "cfads_vs_debt_service")
        )

    sensitivity_summary, sensitivity_sources = _sensitivity_summary(
        _mapping(snapshot.get("sensitivity"))
    )
    monte_summary, monte_sources, risk_signals = _monte_carlo_summary(
        _mapping(snapshot.get("monte_carlo"))
    )

    sections = [
        _section(
            "executive_recommendation",
            "available",
            (
                "Pending IC review. "
                + (
                    f"Persisted financial evidence: {return_summary}."
                    if return_summary
                    else "Financial return evidence is Unavailable."
                )
            ),
            kpi_sources,
        ),
        _section(
            "project_transaction_overview",
            "unavailable",
            "Unavailable — no reviewed canonical project or transaction "
            "metadata is bound to this model.",
            calculation_sources,
        ),
        _section(
            "key_investment_assumptions",
            "available" if assumptions else "unavailable",
            assumption_body
            or "Unavailable — no canonical business-role assumptions were found.",
            assumption_sources,
        ),
        _section(
            "construction_completion_risk",
            "partial" if capex_summary else "unavailable",
            (
                f"Construction profile evidence: {capex_summary}. "
                "Completion-risk mitigants are Unavailable."
                if capex_summary
                else "Unavailable — no canonical capex construction profile."
            ),
            capex_sources,
        ),
        _section(
            "operating_revenue_profile",
            "available" if operating_summary else "unavailable",
            operating_summary
            or "Unavailable — no canonical operating trajectory.",
            operating_sources,
        ),
        _section(
            "financial_returns",
            "available" if return_summary else "unavailable",
            return_summary or "Unavailable — no canonical return KPIs.",
            kpi_sources,
        ),
        _section(
            "funding_capital_structure",
            "available" if capital_summary else "unavailable",
            capital_summary
            or "Unavailable — no canonical capital structure series.",
            capital_sources,
        ),
        _section(
            "debt_service_covenant_analysis",
            "available" if debt_summary else "unavailable",
            debt_summary
            or "Unavailable — no canonical debt service or covenant series.",
            debt_sources,
        ),
        _section(
            "sensitivity_analysis",
            "available" if sensitivity_summary else "unavailable",
            sensitivity_summary
            or "Unavailable — no completed canonical sensitivity analysis "
            "was frozen for this report.",
            sensitivity_sources,
        ),
        _section(
            "monte_carlo_results",
            "available" if monte_summary else "unavailable",
            monte_summary
            or "Unavailable — no completed canonical Monte Carlo result "
            "was frozen for this report.",
            monte_sources,
        ),
        _section(
            "key_risks_mitigants",
            "partial" if risk_signals else "unavailable",
            (
                "Persisted risk signals: "
                + "; ".join(risk_signals)
                + ". Mitigants are Unavailable pending management input."
                if risk_signals
                else "Unavailable — no canonical risk evidence or reviewed "
                "mitigants were provided."
            ),
            [*sensitivity_sources, *monte_sources],
        ),
        _section(
            "approval_conditions",
            "unavailable",
            "Unavailable — no reviewed approval rules are configured.",
            [],
        ),
        _section(
            "final_recommendation",
            "available",
            "Pending IC review",
            kpi_sources,
        ),
    ]
    return {
        "title": "Investment Committee Paper",
        "template_id": _mapping(snapshot.get("template")).get(
            "id",
            "investment-committee-paper",
        ),
        "template_version": _mapping(snapshot.get("template")).get(
            "version",
            "canonical-ic-paper-v1",
        ),
        "persona": dict(_mapping(snapshot.get("persona"))),
        "final_recommendation": "Pending IC review",
        "evidence_hash": snapshot.get("evidence_hash"),
        "sections": sections,
    }
