"""
EXPERIMENTAL — isolated. Deterministic role classification + reconciliation.

The classifier states ONLY what workbook structure can guarantee, and DEFERS the rest
to the LLM's label semantics rather than fabricating a role:

  formula + external ref          -> formula_external          (forced; never an assumption)
  formula + downstream dependents -> formula_derived_value     (forced non-assumption)
  formula + no dependents         -> formula_output            (forced non-assumption)
  text + list data-validation     -> scenario_selector         (forced)
  text (non-numeric)              -> metadata                  (forced non-assumption)
  numeric + downstream dependents -> hardcoded_input           (forced input)
  numeric + no dependents         -> numeric_unwired           (AMBIGUOUS: defer to LLM)

Reconciliation compares the LLM's submitted role to the structural verdict and returns
one of: validated | validated_deferred | reclassified | review.
"""

from __future__ import annotations

from typing import Any

from dependency import has_dependents

ASSUMPTION_ROLES = {"assumption", "hardcoded_input", "scenario_input", "parameter"}
OUTPUT_ROLES = {"output", "formula_output", "hardcoded_display_output", "sensitivity_output"}
DERIVED_ROLES = {"derived", "formula_derived_value"}
META_ROLES = {"metadata", "label", "header", "period_header", "presentation_only", "injection"}
SELECTOR_ROLES = {"scenario_selector"}
SERIES_ROLES = {"financial_series"}
EXTERNAL_ROLES = {"formula_external"}


def family(role: str | None) -> str:
    if role in ASSUMPTION_ROLES:
        return "assumption"
    if role in OUTPUT_ROLES:
        return "output"
    if role in DERIVED_ROLES:
        return "derived"
    if role in META_ROLES:
        return "metadata"
    if role in SELECTOR_ROLES:
        return "selector"
    if role in SERIES_ROLES:
        return "series"
    if role in EXTERNAL_ROLES:
        return "external"
    return "unknown"


def structural_classification(fact: dict[str, Any], ref: str, graph: dict, dv_cells: set[str]) -> dict[str, Any]:
    """Return {category, forced, role, evidence[]} from workbook structure alone."""
    if fact.get("formula"):
        if fact.get("is_external_ref"):
            return {"category": "external", "forced": True, "role": "formula_external",
                    "evidence": [f"cell references another workbook: {fact['formula']}"]}
        dep = has_dependents(graph, ref)
        role = "formula_derived_value" if dep else "formula_output"
        return {"category": "formula", "forced": True, "role": role,
                "evidence": [f"cell contains a formula: {fact['formula']}",
                             f"has_downstream_dependents={dep}"]}

    val = fact.get("raw_value")
    if isinstance(val, str):
        if ref in dv_cells:
            return {"category": "selector", "forced": True, "role": "scenario_selector",
                    "evidence": ["text value governed by a list data-validation dropdown"]}
        return {"category": "metadata", "forced": True, "role": "metadata",
                "evidence": ["non-numeric text value with no formula"]}

    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if ref in dv_cells:
            return {"category": "selector", "forced": True, "role": "scenario_selector",
                    "evidence": ["value governed by a list data-validation dropdown"]}
        if has_dependents(graph, ref):
            return {"category": "input", "forced": True, "role": "hardcoded_input",
                    "evidence": ["hardcoded numeric that feeds downstream formulas"]}
        return {"category": "ambiguous_numeric", "forced": False, "role": "numeric_unwired",
                "evidence": ["hardcoded numeric with no downstream dependents; "
                             "input-vs-display cannot be decided by structure alone"]}

    return {"category": "empty", "forced": False, "role": "unknown",
            "evidence": ["empty or non-scalar cell"]}


def reconcile(submitted_role: str, sc: dict[str, Any]) -> tuple[str, str, list[str]]:
    """Return (validated_role, role_validation_status, evidence)."""
    sf = family(submitted_role)
    ev = list(sc["evidence"])
    cat = sc["category"]

    if cat == "formula":
        if sf in ("derived", "output", "series"):
            # Formula presence is a calculation property, not a competing semantic role.
            # Structure guarantees non-assumption; preserve the LLM's semantic sub-choice.
            return submitted_role, "validated", ev
        return sc["role"], "reclassified", ev + [f"submitted role '{submitted_role}' incompatible with a formula cell"]

    if cat == "external":
        if sf == "series":
            return submitted_role, "validated", ev + [
                "external formula availability is validated independently from series semantics"
            ]
        if sf == "external":
            return "formula_external", "validated", ev
        return "formula_external", "reclassified", ev + [f"external reference cannot be '{submitted_role}'"]

    if cat == "selector":
        if sf == "selector":
            return "scenario_selector", "validated", ev
        return "scenario_selector", "reclassified", ev + [f"data-validation dropdown cannot be '{submitted_role}'"]

    if cat == "metadata":
        if sf == "metadata":
            return submitted_role, "validated", ev
        return "metadata", "reclassified", ev + [f"non-numeric text cannot be '{submitted_role}'"]

    if cat == "input":
        if sf == "assumption":
            return submitted_role, "validated", ev
        return "hardcoded_input", "reclassified", ev + [f"numeric feeds downstream formulas; '{submitted_role}' -> input"]

    if cat == "ambiguous_numeric":
        if sf in ("assumption", "output", "selector", "series"):
            return submitted_role, "validated_deferred", ev + ["deferred to LLM label semantics"]
        if sf == "derived":
            return "hardcoded_display_output", "reclassified", ev + ["no formula present; cannot be formula-derived"]
        if sf == "metadata":
            return submitted_role, "review", ev + ["numeric labelled as metadata; needs review"]
        return submitted_role, "validated_deferred", ev

    return submitted_role, "review", ev
