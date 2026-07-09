"""Tests for calc_engine — financial calculation functions."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from libs.calc_engine.irr import compute_irr
from libs.calc_engine.npv import compute_npv
from libs.calc_engine.dscr import compute_dscr, check_covenant
from libs.calc_engine.monte_carlo import (
    box_muller_normal,
    cholesky_decomposition,
    monte_carlo_simulation,
)


class TestIRR:
    def test_simple_irr(self):
        # Investment of -1000, returns 300/yr for 5 years → IRR ~15.24%
        cash_flows = [-1000, 300, 300, 300, 300, 300]
        result = compute_irr(cash_flows)
        assert result["converged"] is True
        assert result["confidence"] == 1.0
        assert abs(result["result"] - 0.152382) < 0.001

    def test_zero_npv_irr(self):
        # Exact 10% return
        cash_flows = [-1000, 1100]
        result = compute_irr(cash_flows)
        assert result["converged"] is True
        assert abs(result["result"] - 0.10) < 0.0001

    def test_negative_irr(self):
        # Net negative project
        cash_flows = [-1000, 200, 200, 200]
        result = compute_irr(cash_flows)
        assert result["converged"] is True
        assert result["result"] < 0

    def test_insufficient_cash_flows(self):
        result = compute_irr([100])
        assert result["result"] is None
        assert result["confidence"] == 0.0

    def test_empty_cash_flows(self):
        result = compute_irr([])
        assert result["result"] is None

    def test_formula_metadata(self):
        result = compute_irr([-100, 110])
        assert "Newton-Raphson" in result["formula_used"]
        assert "cash_flows_count" in result["inputs"]


class TestNPV:
    def test_simple_npv(self):
        cash_flows = [-1000, 400, 400, 400]
        result = compute_npv(cash_flows, wacc=0.10)
        assert result["confidence"] == 1.0
        # NPV = -1000 + 400/1.1 + 400/1.21 + 400/1.331 ≈ -5.26
        assert abs(result["result"] - (-5.2592)) < 1.0

    def test_npv_positive(self):
        cash_flows = [-1000, 600, 600, 600]
        result = compute_npv(cash_flows, wacc=0.10)
        assert result["result"] > 0

    def test_npv_zero_wacc(self):
        cash_flows = [-100, 50, 50, 50]
        result = compute_npv(cash_flows, wacc=0.0)
        assert abs(result["result"] - 50.0) < 0.01

    def test_npv_with_years(self):
        cash_flows = [-100, 55, 55]
        result = compute_npv(cash_flows, wacc=0.10, start_year=2025)
        assert result["pv_breakdown"][0]["period"] == 2025

    def test_npv_invalid_wacc(self):
        result = compute_npv([-100, 110], wacc=-2)
        assert result["result"] is None

    def test_formula_metadata(self):
        result = compute_npv([-100, 110], wacc=0.1)
        assert "NPV" in result["formula_used"]


class TestDSCR:
    def test_basic_dscr(self):
        ebitda = [100, 120, 130]
        interest = [30, 28, 25]
        principal = [40, 40, 40]
        result = compute_dscr(ebitda, interest, principal)
        assert result["confidence"] == 1.0
        # Year 0: 100/(30+40) = 1.4286
        assert abs(result["annual_dscr"][0]["dscr"] - 1.4286) < 0.001

    def test_zero_debt_service(self):
        ebitda = [100]
        interest = [0]
        principal = [0]
        result = compute_dscr(ebitda, interest, principal)
        assert result["annual_dscr"][0]["dscr"] is None

    def test_dscr_summary(self):
        ebitda = [100, 80, 120]
        interest = [30, 30, 30]
        principal = [20, 20, 20]
        result = compute_dscr(ebitda, interest, principal)
        assert result["result"]["minimum_dscr"] is not None
        assert result["result"]["average_dscr"] is not None

    def test_covenant_green(self):
        result = check_covenant(1.5)
        assert result["result"] == "GREEN"

    def test_covenant_amber(self):
        result = check_covenant(1.30)
        assert result["result"] == "AMBER"

    def test_covenant_breach(self):
        result = check_covenant(1.10)
        assert result["result"] == "BREACH"

    def test_covenant_boundary(self):
        assert check_covenant(1.25)["result"] == "AMBER"
        assert check_covenant(1.35)["result"] == "GREEN"
        assert check_covenant(1.249)["result"] == "BREACH"


class TestMonteCarlo:
    def test_box_muller_count(self):
        samples = box_muller_normal(1000, seed=42)
        assert len(samples) == 1000

    def test_box_muller_distribution(self):
        samples = box_muller_normal(10000, seed=42)
        mean = sum(samples) / len(samples)
        std = (sum((x - mean) ** 2 for x in samples) / len(samples)) ** 0.5
        assert abs(mean) < 0.05  # Should be ~0
        assert abs(std - 1.0) < 0.05  # Should be ~1

    def test_cholesky_identity(self):
        matrix = [[1, 0], [0, 1]]
        L = cholesky_decomposition(matrix)
        assert L == [[1.0, 0.0], [0.0, 1.0]]

    def test_cholesky_correlated(self):
        matrix = [[1.0, 0.5], [0.5, 1.0]]
        L = cholesky_decomposition(matrix)
        assert abs(L[0][0] - 1.0) < 0.001
        assert abs(L[1][0] - 0.5) < 0.001

    def test_monte_carlo_basic(self):
        result = monte_carlo_simulation(
            base_assumptions={"rate": 0.10},
            volatilities={"rate": 0.02},
            n_simulations=5000,
            seed=42,
        )
        assert result["result"]["p10"] is not None
        assert result["result"]["p50"] is not None
        assert result["result"]["p90"] is not None
        assert result["result"]["p10"] < result["result"]["p50"] < result["result"]["p90"]

    def test_monte_carlo_mean_close_to_base(self):
        result = monte_carlo_simulation(
            base_assumptions={"value": 100.0},
            volatilities={"value": 5.0},
            n_simulations=10000,
            seed=42,
        )
        assert abs(result["result"]["mean"] - 100.0) < 1.0

    def test_monte_carlo_histogram(self):
        result = monte_carlo_simulation(
            base_assumptions={"x": 50},
            volatilities={"x": 10},
            n_simulations=5000,
            seed=42,
        )
        assert len(result["histogram"]) == 50
        total_count = sum(b["count"] for b in result["histogram"])
        assert total_count == 5000

    def test_monte_carlo_confidence(self):
        result_high = monte_carlo_simulation(
            base_assumptions={"x": 1},
            volatilities={"x": 0.1},
            n_simulations=10000,
            seed=42,
        )
        result_low = monte_carlo_simulation(
            base_assumptions={"x": 1},
            volatilities={"x": 0.1},
            n_simulations=5000,
            seed=42,
        )
        assert result_high["confidence"] >= result_low["confidence"]

    def test_monte_carlo_var(self):
        result = monte_carlo_simulation(
            base_assumptions={"price": 100},
            volatilities={"price": 20},
            n_simulations=10000,
            seed=42,
        )
        # VaR 95% should be less than mean
        assert result["result"]["var_95"] < result["result"]["mean"]


class TestCalcEngineIntegration:
    """Integration tests using data from the SLNG financial model."""

    def test_irr_from_model_data(self):
        # Approximate cash flows from the model (simplified)
        # Construction: -85M, -330M, -206M (2025-2027)
        # Operations returns from 2028+
        cash_flows = [-85, -330, -206, 8.5, 10.3, 12.2, 14.1, 15.9,
                      17.8, 19.6, 21.5, 23.3, 25.2, 27.0, 28.9,
                      30.7, 32.5, 34.4, 36.2, 38.1]
        result = compute_irr(cash_flows, guess=0.05)
        assert result["converged"] is True
        # Should be in a reasonable range for infrastructure
        assert result["result"] is not None

    def test_npv_from_model_data(self):
        cash_flows = [-85, -330, -206, 8.5, 10.3, 12.2, 14.1, 15.9,
                      17.8, 19.6, 21.5, 23.3, 25.2, 27.0, 28.9,
                      30.7, 32.5, 34.4, 36.2, 38.1]
        result = compute_npv(cash_flows, wacc=0.085, start_year=2025)
        assert result["result"] is not None
        assert result["pv_breakdown"][0]["period"] == 2025

    def test_dscr_from_model_data(self):
        # From model's P&L and Debt_Schedule
        ebitda = [-28.5, -27.3, -26.1, -24.9, -23.8, -22.6, -21.5, -20.3,
                  -19.2, -18.1, -17.0, -15.9, -14.9, -14.0, -12.9, -12.0, -11.0]
        interest = [27.9, 27.9, 27.9, 25.91, 23.92, 21.92, 19.93, 17.94,
                    15.94, 13.95, 11.96, 9.97, 7.97, 5.98, 3.99, 2.0, 0]
        principal = [0, 0, 39.46, 39.46, 39.46, 39.46, 39.46, 39.46,
                     39.46, 39.46, 39.46, 39.46, 39.46, 39.46, 39.46, 39.46, 0]
        result = compute_dscr(ebitda, interest, principal)
        assert result["result"]["minimum_dscr"] is not None
        assert len(result["annual_dscr"]) == 17
