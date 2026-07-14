"""
EXPERIMENTAL — isolated. Deterministic validator: SOURCE + ROLE + DEPENDENCY.

The validator re-reads the workbook and trusts only the workbook. It answers two
independent questions per candidate:

  1. SOURCE   — does the submitted value actually exist at the cited cell?
                (missing/error/external caches are UNAVAILABLE; a value there is fabricated)
  2. ROLE     — is the submitted role consistent with workbook structure?
                (a formula cell can never be a hardcoded assumption; text can never be a
                 numeric assumption; a numeric feeding formulas is an input; a lone numeric
                 is ambiguous and defers to the LLM.)

A candidate can be source-valid yet role-invalid ("reclassified").
"""

from __future__ import annotations

import math
from typing import Any

from workbook_tools import WorkbookToolset, ToolError
from dependency import build_dependency_graph
from roles import structural_classification, reconcile, family

_UNAVAILABLE = {"formula_no_cache", "formula_external", "formula_error"}


def _values_match(submitted: Any, actual: Any) -> bool:
    if submitted is None and actual is None:
        return True
    if isinstance(submitted, (int, float)) and isinstance(actual, (int, float)) \
            and not isinstance(submitted, bool) and not isinstance(actual, bool):
        return math.isclose(float(submitted), float(actual), rel_tol=1e-9, abs_tol=1e-9)
    return str(submitted).strip() == str(actual).strip()


def _submitted_value(cand: dict) -> Any:
    return cand.get("raw_value", cand.get("value"))


def _submitted_role(cand: dict) -> str:
    return cand.get("submitted_role") or cand.get("candidate_type") or "unknown"


def validate_candidate(tools: WorkbookToolset, graph: dict, cand: dict[str, Any]) -> dict[str, Any]:
    cid = cand.get("candidate_id")
    submitted_role = _submitted_role(cand)
    warnings: list[str] = []
    rejected: list[str] = []

    refs = cand.get("source_references") or []
    if not refs:
        return _result(cid, submitted_role, source="rejected", overall="rejected",
                       rejected=["no source_references"], review=True,
                       invalid_source=True, rejection_reason="no_source", cand=cand)

    ref = refs[0]
    sheet, cell = ref.get("sheet_name"), ref.get("cell")
    try:
        fact = tools.get_cell(sheet, cell)
    except ToolError as e:
        return _result(cid, submitted_role, source="rejected", overall="rejected",
                       rejected=[e.message], review=True, warnings=[e.code],
                       invalid_source=True, rejection_reason="bad_reference", cand=cand)

    src_ref = fact["source_reference"]
    submitted = _submitted_value(cand)
    actual = fact["raw_value"]
    unavailable = fact["formula_status"] in _UNAVAILABLE

    # ---- SOURCE validation ----
    rejection_reason = None
    if unavailable:
        if submitted is not None:
            rejected.append(f"value {submitted!r} submitted for {src_ref} but the cell value is "
                            f"UNAVAILABLE ({fact['formula_status']}); must remain null, never 0")
            source_status = "rejected"
            validated_value = None
            rejection_reason = "unavailable_fabrication"
        else:
            warnings.append(f"value_unavailable_{fact['formula_status']}_left_null")
            source_status = "validated_null"
            validated_value = None
    else:
        if submitted is None:
            warnings.append("submitted_value_null_but_workbook_has_value")
            source_status = "validated"
            validated_value = actual
        elif _values_match(submitted, actual):
            source_status = "validated"
            validated_value = actual
        else:
            rejected.append(f"submitted {submitted!r} != workbook {actual!r} at {src_ref}")
            source_status = "rejected"
            validated_value = actual
            rejection_reason = "value_mismatch"

    # ---- ROLE validation ----
    dv_cells = tools.data_validation_cells(sheet)
    sc = structural_classification(fact, src_ref, graph, dv_cells)
    validated_role, role_status, role_evidence = reconcile(submitted_role, sc)

    dependency_evidence = {
        "precedents": graph.get("precedents", {}).get(src_ref, []),
        "dependents": graph.get("dependents", {}).get(src_ref, []),
        "is_external_ref": fact.get("is_external_ref", False),
    }

    # ---- overall ----
    if source_status == "rejected":
        overall = "rejected"
    elif role_status == "reclassified":
        overall = "reclassified"
    elif role_status == "review":
        overall = "review_required"
    elif source_status == "validated_null":
        overall = "validated_null"
    else:
        overall = "validated"

    review = overall in ("rejected", "reclassified", "review_required", "validated_null") \
        or role_status == "validated_deferred"

    confidence = {"validated": 0.95, "validated_null": 0.6, "reclassified": 0.4,
                  "review_required": 0.4, "rejected": 0.0}.get(overall, 0.3)

    return {
        "candidate_id": cid,
        "original_label": cand.get("original_label"),
        "submitted_value": submitted,
        "is_formula": fact.get("formula") is not None,
        "source_reference": src_ref,
        "source_validation_status": source_status,
        "submitted_role": submitted_role,
        "validated_role": validated_role,
        "role_validation_status": role_status,
        "role_evidence": role_evidence,
        "validation_status": overall,
        "validated_value": validated_value,
        "formula_status": fact["formula_status"],
        "data_type": fact["data_type"],
        "number_format": fact["number_format"],
        "validation_confidence": confidence,
        "validation_warnings": warnings,
        "rejected_claims": rejected,
        "rejection_reason": rejection_reason,
        "invalid_source": False,
        "structural_evidence": sc["evidence"],
        "dependency_evidence": dependency_evidence,
        "review_required": review,
    }


def _result(cid, submitted_role, *, source, overall, rejected=None, review=False,
            warnings=None, invalid_source=False, rejection_reason=None, cand=None):
    cand = cand or {}
    return {
        "candidate_id": cid,
        "original_label": cand.get("original_label"),
        "submitted_value": _submitted_value(cand) if cand else None,
        "is_formula": False,
        "source_reference": None,
        "source_validation_status": source,
        "submitted_role": submitted_role,
        "validated_role": None,
        "role_validation_status": "not_evaluated",
        "role_evidence": [],
        "validation_status": overall,
        "validated_value": None,
        "formula_status": None,
        "validation_confidence": 0.0,
        "validation_warnings": warnings or [],
        "rejected_claims": rejected or [],
        "rejection_reason": rejection_reason,
        "invalid_source": invalid_source,
        "structural_evidence": [],
        "dependency_evidence": {},
        "review_required": review,
    }


def validate_extraction(tools: WorkbookToolset, extraction: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate every candidate across all buckets. Builds the dependency graph once."""
    graph = build_dependency_graph(tools.iter_formulas(), tools.defined_names())
    buckets = ("all_assumption_candidates", "parameter_candidates", "derived_value_candidates",
               "output_candidates", "financial_series_candidates", "unclassified_inputs",
               "review_candidates")
    results = []
    for b in buckets:
        for cand in extraction.get(b, []) or []:
            cand = dict(cand)
            cand.setdefault("_bucket", b)
            r = validate_candidate(tools, graph, cand)
            r["_bucket"] = b
            results.append(r)
    return results
