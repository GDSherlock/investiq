"""Behavior tests for the deterministic request-scoped workbook index."""

import os
import sys

import openpyxl
from openpyxl.workbook.defined_name import DefinedName


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from workbook_index import WorkbookIndexBuilder
from workbook_tools import WorkbookToolset


def _indexed_workbook(tmp_path):
    path = tmp_path / "indexed.xlsx"
    workbook = openpyxl.Workbook()
    inputs = workbook.active
    inputs.title = "Inputs"
    inputs["A1"] = "Tax rate"
    inputs["B1"] = "Value"
    inputs["A2"] = "Base tax"
    inputs["B2"] = 0.25
    inputs["A3"].number_format = "General"

    calc = workbook.create_sheet("Calc")
    calc["A1"] = "Double tax"
    calc["B1"] = "=B2*2"
    calc["A2"] = "Linked tax"
    calc["B2"] = "=Inputs!B2"
    calc["A3"].number_format = "General"

    workbook.defined_names.add(
        DefinedName("TaxRate", attr_text="Inputs!$B$2")
    )
    workbook.save(path)
    return WorkbookToolset(file_path=str(path))


def test_index_is_bound_to_workbook_and_inventory_is_deterministic(tmp_path):
    tools = _indexed_workbook(tmp_path)

    index = WorkbookIndexBuilder().build(tools)

    assert index.workbook_version == tools.workbook_version
    assert index.content_sheets == ("Inputs", "Calc")
    assert index.required_ranges == {"Inputs": "A1:B2", "Calc": "A1:B2"}
    assert index.non_empty_cell_count == 8
    assert [fact["source_reference"] for fact in index.facts["Inputs"]] == [
        "Inputs!A1",
        "Inputs!B1",
        "Inputs!A2",
        "Inputs!B2",
    ]


def test_index_records_named_ranges_and_cross_sheet_dependencies(tmp_path):
    index = WorkbookIndexBuilder().build(_indexed_workbook(tmp_path))

    assert index.defined_names["TaxRate"] == "Inputs!$B$2"
    assert index.dependency_graph["precedents"]["Calc!B2"] == ["Inputs!B2"]
    assert index.related_references("Calc", "A1:B2") == ("Inputs!B2",)


def test_facts_for_range_returns_backend_evidence_in_source_order(tmp_path):
    index = WorkbookIndexBuilder().build(_indexed_workbook(tmp_path))

    facts = index.facts_for_range("Calc", "A1:B2")

    assert [fact["source_reference"] for fact in facts] == [
        "Calc!A1",
        "Calc!B1",
        "Calc!A2",
        "Calc!B2",
    ]
    assert facts[-1]["formula"] == "=Inputs!B2"
