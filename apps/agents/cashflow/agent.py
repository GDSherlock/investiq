"""
CashFlowAgent — P10/P50/P90, DSCR tracking.
Output: CFAnalysis + CovenantStatus
"""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from apps.agents.base import BaseAgent
from libs.calc_engine.npv import compute_npv
from libs.calc_engine.irr import compute_irr
from libs.calc_engine.dscr import compute_dscr, check_covenant


class CashFlowAgent(BaseAgent):
    name = "CashFlowAgent"
    description = "Analyzes cash flows, computes P10/P50/P90 and tracks DSCR covenants"
    tools = ["calc_engine", "dscr_monitor"]
    output_types = ["CFAnalysis", "CovenantStatus"]

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        model_data = context.get("model_data", {})

        cf_data = model_data.get("cash_flows", {})
        pnl_data = model_data.get("pnl", {})
        debt_data = model_data.get("debt_schedule", {})
        returns = model_data.get("returns", {})
        years = cf_data.get("years", [])

        # Extract series
        ebitda = self._extract_series(pnl_data, "EBITDA")
        interest = self._extract_series(debt_data, "Interest charge")
        principal = self._extract_series(debt_data, "(Scheduled repayment)")

        # DSCR calculation
        dscr_result = compute_dscr(ebitda, interest, principal)

        # Covenant status per year
        covenant_statuses = []
        for entry in dscr_result.get("annual_dscr", []):
            if entry.get("dscr") is not None:
                covenant = check_covenant(entry["dscr"])
                idx = entry["year_index"]
                covenant_statuses.append({
                    "year": years[idx] if idx < len(years) else idx,
                    "dscr": entry["dscr"],
                    "status": covenant["result"],
                })

        # NPV and IRR from returns
        npv = irr = None
        for m in returns.get("metrics", []):
            if "NPV" in m.get("metric", ""):
                npv = m.get("base_case")
            if "Project IRR" in m.get("metric", ""):
                irr = m.get("base_case")

        return self._build_result(
            data={
                "cf_analysis": {
                    "years": years,
                    "cash_flows": cf_data.get("data", {}),
                    "npv": npv,
                    "irr": irr,
                },
                "dscr": dscr_result,
                "covenant_status": covenant_statuses,
            },
            confidence=1.0,
        )

    @staticmethod
    def _extract_series(data: dict, key: str) -> list[float]:
        values = data.get("data", {}).get(key, [])
        return [float(v) if v else 0.0 for v in values]
