"""TDD for extended workbook tools: metadata, named ranges, data validations,
error-cache handling, external-ref detection, hidden-sheet access, formula graph."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from workbook_tools import WorkbookToolset
from dependency import build_dependency_graph, has_dependents

FX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures"))


def tools(name):
    return WorkbookToolset(file_path=os.path.join(FX, f"{name}.xlsx"))


# ---- error / no-cache / external handling (integrity invariants) ----
def test_error_cache_is_unavailable_not_a_value():
    t = tools("hidden_named_injection")
    fact = t.get_cell("Model", "C6")           # =[1]Rates!B2 -> cached '#N/A'
    assert fact["raw_value"] is None           # error is NOT a value
    assert fact["raw_value"] != 0              # and definitely not coerced to 0
    assert fact["is_external_ref"] is True
    assert fact["formula_status"] in ("formula_error", "formula_external")


def test_missing_cache_stays_null():
    t = tools("hidden_named_injection")
    fact = t.get_cell("Model", "C5")           # cache stripped -> None
    assert fact["formula"] is not None
    assert fact["raw_value"] is None
    assert fact["formula_status"] == "formula_no_cache"


def test_hidden_sheet_cell_is_readable():
    t = tools("hidden_named_injection")
    fact = t.get_cell("Confidential", "C3")
    assert fact["raw_value"] == 12.5
    assert fact["formula_status"] == "static_value"


def test_formula_with_cache_reports_cached_value():
    t = tools("no_assumptions_sheet")
    fact = t.get_cell("Funding", "C5")         # =C3*(1+C4) -> 432
    assert fact["formula"] is not None
    assert fact["raw_value"] == 432
    assert fact["formula_status"] == "formula_with_cached_value"


# ---- metadata / named ranges / data validation ----
def test_workbook_metadata_named_ranges_and_external():
    t = tools("hidden_named_injection")
    md = t.get_workbook_metadata()
    names = {n["name"] for n in md["named_ranges"]}
    assert {"throughput", "availability"} <= names
    assert md["external_links"], "external link must be reported"
    assert "Confidential" in [s["name"] for s in md["sheets"] if s["state"] == "hidden"]


def test_data_validations():
    t = tools("hidden_named_injection")
    dvs = t.get_data_validations("Model")
    assert any("Fixed" in (dv.get("formula1") or "") for dv in dvs)


def test_list_sheets_includes_hidden_state():
    t = tools("hidden_named_injection")
    sheets = {s["name"]: s["state"] for s in t.list_sheets()["sheets"]}
    assert sheets["Confidential"] == "hidden"


# ---- dependency graph over a real fixture ----
def test_graph_dependents_across_sheets_and_named_range():
    t = tools("hidden_named_injection")
    g = build_dependency_graph(t.iter_formulas(), t.defined_names())
    # Model!C5 = Confidential!C3 * throughput(=Model!C3)
    assert set(g["precedents"]["Model!C5"]) == {"Confidential!C3", "Model!C3"}
    assert "Model!C5" in g["dependents"]["Confidential!C3"]
    assert "Model!C6" in g["external_refs"]


def test_graph_input_has_dependents_output_does_not():
    t = tools("no_assumptions_sheet")
    g = build_dependency_graph(t.iter_formulas(), t.defined_names())
    assert has_dependents(g, "Funding!C5")     # derived intermediate, feeds Calc/Summary
    assert has_dependents(g, "Funding!C3")     # base capex feeds Funding!C5
    assert not has_dependents(g, "Summary!C6")  # leaf output
    assert not has_dependents(g, "Funding!C6")  # debt margin: unwired input (no dependents)
