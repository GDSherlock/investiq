"""TDD for the integrated deterministic validator (source + role + dependency)."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from workbook_tools import WorkbookToolset
from dependency import build_dependency_graph
from validator import validate_candidate
from roles import family

FX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures"))


class V:
    def __init__(self, name):
        self.t = WorkbookToolset(file_path=os.path.join(FX, f"{name}.xlsx"))
        self.g = build_dependency_graph(self.t.iter_formulas(), self.t.defined_names())

    def run(self, cand):
        return validate_candidate(self.t, self.g, cand)


def cand(cid, sheet, cell, raw_value, role, **kw):
    d = {"candidate_id": cid, "submitted_role": role, "raw_value": raw_value,
         "source_references": [{"sheet_name": sheet, "cell": cell}]}
    d.update(kw)
    return d


def test_valid_hardcoded_assumption():
    r = V("no_assumptions_sheet").run(cand("a", "Funding", "C3", 400, "hardcoded_input"))
    assert r["source_validation_status"] == "validated"
    assert r["validation_status"] == "validated"
    assert family(r["validated_role"]) == "assumption"
    assert r["validated_value"] == 400


def test_fabricated_value_rejected():
    r = V("no_assumptions_sheet").run(cand("b", "Funding", "C3", 999, "hardcoded_input"))
    assert r["source_validation_status"] == "rejected"
    assert r["validation_status"] == "rejected"


def test_correct_cell_wrong_role_reclassified():
    # value 432 is CORRECT for Funding!C5, but the cell is a formula -> not an assumption.
    r = V("no_assumptions_sheet").run(cand("c", "Funding", "C5", 432, "hardcoded_input"))
    assert r["source_validation_status"] == "validated"          # value matches
    assert r["role_validation_status"] == "reclassified"          # role does not
    assert family(r["validated_role"]) != "assumption"
    assert r["validation_status"] == "reclassified"


def test_metadata_submitted_as_assumption_reclassified():
    # correct value (project name), but a text/metadata cell cannot be an assumption
    r = V("no_assumptions_sheet").run(cand("d", "Overview", "C3", "Riverbend Solar 120MW", "hardcoded_input"))
    assert r["source_validation_status"] == "validated"
    assert family(r["validated_role"]) == "metadata"
    assert r["validation_status"] == "reclassified"


def test_fabricating_value_for_uncached_formula_rejected():
    r = V("hidden_named_injection").run(cand("e", "Model", "C5", 100, "formula_derived_value"))
    assert r["source_validation_status"] == "rejected"
    assert r["validation_status"] == "rejected"


def test_honest_null_for_uncached_formula_not_zero():
    r = V("hidden_named_injection").run(cand("f", "Model", "C5", None, "formula_derived_value"))
    assert r["validated_value"] is None
    assert r["source_validation_status"] in ("validated_null", "validated")
    assert r["validation_status"] != "rejected"


def test_external_ref_value_fabrication_rejected():
    r = V("hidden_named_injection").run(cand("g", "Model", "C6", 5.0, "formula_derived_value"))
    assert r["source_validation_status"] == "rejected"


def test_missing_source_rejected():
    r = V("no_assumptions_sheet").run(
        {"candidate_id": "h", "submitted_role": "hardcoded_input", "raw_value": 1, "source_references": []})
    assert r["validation_status"] == "rejected"


def test_bad_sheet_reference_rejected():
    r = V("no_assumptions_sheet").run(cand("i", "Nope", "C3", 1, "hardcoded_input"))
    assert r["validation_status"] == "rejected"


def test_dependency_evidence_present_for_input():
    r = V("no_assumptions_sheet").run(cand("j", "Funding", "C3", 400, "hardcoded_input"))
    assert "Funding!C5" in r["dependency_evidence"]["dependents"]
