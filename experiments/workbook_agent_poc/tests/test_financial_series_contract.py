"""Contract tests for compact financial-series descriptor submissions."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extraction_contract import SUBMIT_RESULT_SCHEMA, SYSTEM_PROMPT


def test_submit_contract_accepts_descriptors_without_workbook_arrays():
    schema = SUBMIT_RESULT_SCHEMA["properties"]["financial_series"]["items"]

    assert {
        "series_id",
        "label",
        "semantic_role",
        "business_role",
        "category",
        "unit",
        "frequency",
        "period_range",
        "value_range",
        "scenario",
        "entity",
        "currency",
        "label_reference",
    }.issubset(schema["properties"])
    assert schema["properties"]["semantic_role"]["const"] == "financial_series"
    assert set(schema["required"]) == {
        "series_id",
        "label",
        "semantic_role",
        "business_role",
        "category",
        "unit",
        "frequency",
        "period_range",
        "value_range",
    }
    assert "period_axis" not in schema["properties"]
    assert "value_axis" not in schema["properties"]
    assert "calculation_type" not in schema["properties"]
    assert "formula_pattern" not in schema["properties"]


def test_output_candidates_require_registered_business_role():
    schema = SUBMIT_RESULT_SCHEMA["properties"]["output_candidates"]["items"]

    assert "business_role" in schema["properties"]
    assert "business_role" in schema["required"]
    assert "unclassified" in schema["properties"]["business_role"]["enum"]


def test_prompt_forbids_representative_cells_and_keeps_formula_semantics_independent():
    prompt = SYSTEM_PROMPT.lower()

    assert "complete contiguous period range" in prompt
    assert "complete contiguous value range" in prompt
    assert "never use a single representative cell" in prompt
    assert "do not submit periods[] or values[]" in prompt
    assert "backend will materialize" in prompt
    assert "sheet name" in prompt
    assert "same number of cells" in prompt
    assert "formula-based" in prompt and "financial_series" in prompt
    assert "scenario" in prompt and "sensitivity" in prompt
    assert "infer missing values" in prompt
