"""Tests for the Excel parser tool."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from libs.tools.excel_parser import ExcelParser
from libs.tools.assumption_mapper import AssumptionMapper


SAMPLE_FILE = os.path.join(os.path.dirname(__file__), "..", "Financial_Model_Data.xlsx")


@pytest.fixture
def parser():
    if not os.path.exists(SAMPLE_FILE):
        pytest.skip("Sample Excel file not found")
    return ExcelParser(file_path=SAMPLE_FILE)


class TestExcelParser:
    def test_sheet_names(self, parser):
        sheets = parser.sheet_names
        assert "Cover" in sheets
        assert "Assumptions" in sheets
        assert "Revenue" in sheets
        assert "CashFlows" in sheets
        assert "Returns" in sheets

    def test_parse_all(self, parser):
        data = parser.parse_all()
        assert "sheets" in data
        assert "cover" in data
        assert "assumptions" in data
        assert "revenue" in data
        assert "returns" in data

    def test_parse_cover(self, parser):
        data = parser.parse_all()
        cover = data["cover"]
        assert "Project" in cover or len(cover) > 0

    def test_parse_assumptions(self, parser):
        data = parser.parse_all()
        assumptions = data["assumptions"]
        assert len(assumptions) > 20  # Should have many assumptions
        # Check structure
        for a in assumptions:
            assert "name" in a
            assert "value" in a

    def test_parse_returns(self, parser):
        data = parser.parse_all()
        returns = data["returns"]
        assert "metrics" in returns
        assert len(returns["metrics"]) > 5

    def test_health_check(self, parser):
        health = parser.health_check()
        assert "health_score" in health
        assert health["health_score"] >= 0
        assert health["health_score"] <= 100
        assert health["status"] in ["HEALTHY", "DEGRADED", "UNHEALTHY"]

    def test_parse_sensitivity(self, parser):
        data = parser.parse_all()
        sens = data["sensitivity"]
        assert "one_way" in sens
        assert len(sens["one_way"]) > 0

    def test_parse_time_series_revenue(self, parser):
        data = parser.parse_all()
        revenue = data["revenue"]
        assert "years" in revenue
        assert "data" in revenue
        assert len(revenue["years"]) > 0


class TestAssumptionMapper:
    def test_categorize_wacc(self):
        assert AssumptionMapper.categorize("WACC (unlevered)") == "WACC"

    def test_categorize_irr(self):
        assert AssumptionMapper.categorize("Equity IRR hurdle") == "IRR"

    def test_categorize_dscr(self):
        assert AssumptionMapper.categorize("DSCR covenant (min)") == "DSCR"

    def test_categorize_revenue(self):
        assert AssumptionMapper.categorize("Regasification fee (base)") == "REVENUE"

    def test_categorize_debt(self):
        assert AssumptionMapper.categorize("Debt ratio") == "DEBT"

    def test_categorize_tax(self):
        assert AssumptionMapper.categorize("Corporate tax rate") == "TAX"

    def test_categorize_unknown(self):
        assert AssumptionMapper.categorize("Some random thing") == "OTHER"

    def test_map_all(self):
        assumptions = [
            {"name": "WACC (unlevered)", "value": 0.085},
            {"name": "Debt ratio", "value": 0.65},
        ]
        mapped = AssumptionMapper.map_all(assumptions)
        assert mapped[0]["category"] == "WACC"
        assert mapped[1]["category"] == "DEBT"

    def test_get_by_category(self):
        assumptions = [
            {"name": "WACC (unlevered)", "value": 0.085},
            {"name": "Debt ratio", "value": 0.65},
            {"name": "Equity required return", "value": 0.135},
        ]
        wacc_items = AssumptionMapper.get_by_category(assumptions, "WACC")
        assert len(wacc_items) == 1

    def test_detect_hardcoded(self):
        assumptions = [
            {"name": "A", "value": 1, "source": "Report"},
            {"name": "B", "value": 2, "source": ""},
            {"name": "C", "value": 3},
        ]
        hardcoded = AssumptionMapper.detect_hardcoded(assumptions)
        assert len(hardcoded) == 2
