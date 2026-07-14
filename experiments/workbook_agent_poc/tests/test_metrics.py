"""TDD for evaluation metrics: confirmed-role counting, discovery P/R/F1, integrity."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from metrics import score_fixture

GT = {
    "declarations": [
        {"source_reference": "S!C1", "role": "hardcoded_input"},
        {"source_reference": "S!C2", "role": "hardcoded_input"},
        {"source_reference": "S!C3", "role": "formula_output"},
        {"source_reference": "S!C4", "role": "metadata"},
        {"source_reference": "S!C5", "role": "hardcoded_input"},
    ],
    "expected_assumptions": [{"source_reference": r} for r in ("S!C1", "S!C2", "S!C5")],
    "expected_outputs": [{"source_reference": "S!C3"}],
    "must_not_classify_as_assumption": ["S!C3", "S!C4"],
    "injection_cells": [],
    "expected_unknown_labels": [{"original_label": "尾期系数", "source_reference": "S!C5"}],
    "expected_external_refs": [],
}
COV = {"total_sheets": 1, "inspected_sheets": 1, "hidden_sheets_total": 0, "hidden_sheets_inspected": 0,
       "content_sheets": ["S"], "regions_read_sheets": ["S"], "formula_sheets": ["S"],
       "metadata_inspected": True, "named_ranges_present": False, "external_links": []}


def R(ref, vrole, status, src="validated", is_formula=False, fs="static_value", val=1, rr=None, inv=False, label=None):
    return {"source_reference": ref, "validated_role": vrole, "validation_status": status,
            "source_validation_status": src, "is_formula": is_formula, "formula_status": fs,
            "validated_value": val, "invalid_source": inv, "rejection_reason": rr, "original_label": label}


def base_results():
    return [
        R("S!C1", "hardcoded_input", "validated", val=10, label="Growth"),                 # TP
        R("S!C5", "hardcoded_input", "validated", val=0.87, label="尾期系数"),             # TP + unknown
        R("S!C3", "formula_output", "reclassified", is_formula=True, fs="formula_with_cached_value", val=5, label="IRR"),  # output submitted as assumption -> reclassified
        R("S!C4", "metadata", "reclassified", val="Proj", label="Name"),                   # metadata submitted as assumption -> reclassified
        R("S!C1", "hardcoded_input", "rejected", src="rejected", val=10, rr="value_mismatch", label="Growth"),  # fabricated dup, rejected
    ]


def test_discovery_precision_recall():
    m = score_fixture(GT, base_results(), COV)
    ad = m["assumption_discovery"]
    assert ad["true_positive"] == 2 and ad["false_negative"] == 1   # C2 missed
    assert ad["precision"] == 1.0
    assert round(ad["recall"], 3) == 0.667


def test_reclassified_not_counted_as_assumption():
    m = score_fixture(GT, base_results(), COV)
    rc = m["role_classification"]
    assert rc["formula_derived_confirmed_as_assumption"] == 0
    assert rc["metadata_confirmed_as_assumption"] == 0
    assert rc["output_confirmed_as_assumption"] == 0


def test_integrity_fabrication_detected_not_accepted():
    m = score_fixture(GT, base_results(), COV)
    ig = m["integrity"]
    assert ig["fabricated_values_detected"] == 1
    assert ig["fabricated_values_accepted"] == 0
    assert m["assumption_discovery"]["value_accuracy_available"] == 1.0


def test_unknown_label_preserved():
    m = score_fixture(GT, base_results(), COV)
    assert m["integrity"]["unknown_label_preservation"] == 1.0


def test_output_confirmed_as_assumption_is_flagged_when_it_happens():
    # If a formula OUTPUT is wrongly CONFIRMED as an assumption, the metric must catch it.
    bad = base_results()
    bad[2] = R("S!C3", "hardcoded_input", "validated", is_formula=True, fs="formula_with_cached_value", val=5, label="IRR")
    m = score_fixture(GT, bad, COV)
    assert m["role_classification"]["formula_derived_confirmed_as_assumption"] == 1
    assert m["role_classification"]["output_confirmed_as_assumption"] == 1
