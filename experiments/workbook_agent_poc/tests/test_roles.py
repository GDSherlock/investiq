"""TDD for deterministic role classification + reconciliation against the LLM's submitted role.

Key guarantees under test:
  * A formula cell can NEVER be confirmed as a hardcoded assumption (reclassified).
  * A text/metadata cell can NEVER be confirmed as a numeric assumption (reclassified).
  * A numeric that FEEDS downstream formulas is forced to hardcoded_input.
  * A lone numeric (no dependents) is genuinely ambiguous -> defer to the LLM's label
    semantics (structure must not fabricate a role).
  * External references are reclassified to formula_external (never an assumption).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from workbook_tools import WorkbookToolset
from dependency import build_dependency_graph
from roles import structural_classification, reconcile, family

FX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures"))


class Ctx:
    def __init__(self, name):
        self.t = WorkbookToolset(file_path=os.path.join(FX, f"{name}.xlsx"))
        self.g = build_dependency_graph(self.t.iter_formulas(), self.t.defined_names())

    def classify(self, sheet, cell):
        fact = self.t.get_cell(sheet, cell)
        ref = f"{sheet}!{cell}"
        dv = self.t.data_validation_cells(sheet)
        return structural_classification(fact, ref, self.g, dv)

    def reconcile(self, sheet, cell, submitted):
        return reconcile(submitted, self.classify(sheet, cell))


def test_formula_with_dependents_is_derived_not_assumption():
    c = Ctx("no_assumptions_sheet")
    role, status, _ = c.reconcile("Funding", "C5", "hardcoded_input")   # capex incl. contingency
    assert status == "reclassified"
    assert family(role) != "assumption"
    assert role == "formula_derived_value"


def test_leaf_formula_output_validated_when_submitted_output():
    c = Ctx("no_assumptions_sheet")
    role, status, _ = c.reconcile("Summary", "C6", "output")           # total project cost = leaf formula
    assert status == "validated"
    assert role in ("output", "formula_output")


def test_formula_submitted_as_assumption_is_reclassified_out_of_assumption():
    c = Ctx("no_assumptions_sheet")
    role, status, _ = c.reconcile("Summary", "C6", "hardcoded_input")
    assert status == "reclassified"
    assert family(role) != "assumption"


def test_numeric_feeding_formulas_is_forced_input():
    c = Ctx("no_assumptions_sheet")
    role, status, _ = c.reconcile("Funding", "C3", "output")           # base capex feeds C5
    assert status == "reclassified"
    assert role == "hardcoded_input"


def test_numeric_input_submitted_as_assumption_validated():
    c = Ctx("no_assumptions_sheet")
    role, status, _ = c.reconcile("Funding", "C3", "hardcoded_input")
    assert status == "validated"
    assert family(role) == "assumption"


def test_metadata_text_cannot_be_assumption():
    c = Ctx("no_assumptions_sheet")
    role, status, _ = c.reconcile("Overview", "C3", "hardcoded_input")  # "Report date"
    assert status == "reclassified"
    assert family(role) == "metadata"


def test_lone_numeric_defers_to_llm_semantics():
    c = Ctx("no_assumptions_sheet")
    # Project IRR (Summary!C3) is a static numeric with no dependents -> ambiguous.
    as_out = c.reconcile("Summary", "C3", "hardcoded_display_output")
    as_in = c.reconcile("Summary", "C3", "hardcoded_input")
    assert as_out[1] in ("validated", "validated_deferred")
    assert family(as_out[0]) == "output"
    assert as_in[1] in ("validated", "validated_deferred")   # structure cannot refute a lone numeric
    assert family(as_in[0]) == "assumption"


def test_external_reference_cannot_be_assumption():
    c = Ctx("hidden_named_injection")
    role, status, _ = c.reconcile("Model", "C6", "hardcoded_input")
    assert status == "reclassified"
    assert role == "formula_external"


def test_data_validation_cell_is_selector():
    c = Ctx("hidden_named_injection")
    role, status, _ = c.reconcile("Model", "C7", "scenario_selector")   # Fee basis dropdown
    assert status == "validated"
    assert role == "scenario_selector"
    # and if the LLM wrongly calls the dropdown an assumption:
    role2, status2, _ = c.reconcile("Model", "C7", "hardcoded_input")
    assert status2 == "reclassified"
    assert role2 == "scenario_selector"


def test_injection_text_cell_is_metadata_not_assumption():
    c = Ctx("hidden_named_injection")
    role, status, _ = c.reconcile("Notes", "B2", "hardcoded_input")
    assert status == "reclassified"
    assert family(role) == "metadata"


def test_hidden_sheet_numeric_input_is_assumption():
    c = Ctx("hidden_named_injection")
    role, status, _ = c.reconcile("Confidential", "C3", "hardcoded_input")  # feeds Model!C5
    assert family(role) == "assumption"
