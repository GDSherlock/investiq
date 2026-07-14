"""TDD for the bounded formula dependency parser."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dependency import parse_formula_refs


def P(formula, sheet, names=None):
    return parse_formula_refs(formula, sheet, names or {})


def test_same_sheet_refs():
    r = P("=C6*(1+C4)", "Operations")
    assert set(r["precedents"]) == {"Operations!C6", "Operations!C4"}
    assert r["external"] == []


def test_cross_sheet_refs():
    r = P("=Funding!C5*Funding!C7", "Calc")
    assert set(r["precedents"]) == {"Funding!C5", "Funding!C7"}


def test_mixed_same_and_cross_sheet():
    r = P("=Funding!C5-C4", "Calc")
    assert set(r["precedents"]) == {"Funding!C5", "Calc!C4"}


def test_pure_constants_have_no_refs():
    assert P("=1+0.35", "Summary")["precedents"] == []
    assert P("=8760*0.42*120", "测算底稿")["precedents"] == []


def test_unicode_sheet_reference():
    r = P("=业务测算!C6*(1+0.13)", "测算底稿")
    assert set(r["precedents"]) == {"业务测算!C6"}


def test_absolute_references_are_normalized():
    r = P("=$C5*D$4*10", "Sensitivity")
    assert set(r["precedents"]) == {"Sensitivity!C5", "Sensitivity!D4"}


def test_external_reference_recorded_not_fabricated():
    r = P("=[1]Rates!B2", "Model")
    assert r["external"], "external ref must be recorded"
    # must NOT invent an internal precedent for an external reference
    assert r["precedents"] == []


def test_named_range_resolves_to_target():
    r = P("=Confidential!C3*throughput", "Model", {"throughput": "Model!$C$3"})
    assert set(r["precedents"]) == {"Confidential!C3", "Model!C3"}


def test_unknown_identifier_is_not_a_precedent():
    # a bare function/identifier that is not a defined name must not become a ref
    r = P("=MAX(C1,C2)", "S", {})
    assert set(r["precedents"]) == {"S!C1", "S!C2"}  # MAX not treated as a ref
