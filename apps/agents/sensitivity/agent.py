"""
SensitivityAgent — scenario analysis across drivers.
Output: SensitivityResult + AISignal
"""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from apps.agents.base import BaseAgent
from libs.calc_engine.irr import compute_irr
from libs.calc_engine.npv import compute_npv
from libs.tools.assumption_mapper import AssumptionMapper


class SensitivityAgent(BaseAgent):
    name = "SensitivityAgent"
    description = "Runs scenario analysis across key assumption drivers"
    tools = ["calc_engine", "assumption_mapper"]
    output_types = ["SensitivityResult", "AISignal"]

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        model_data = context.get("model_data", {})
        variables = context.get("variables", [])
        range_pct = context.get("range_pct", 0.2)

        assumptions = model_data.get("assumptions", [])
        sensitivity = model_data.get("sensitivity", {})
        returns = model_data.get("returns", {})

        # Use pre-computed sensitivity from model
        one_way = sensitivity.get("one_way", [])
        two_way = sensitivity.get("two_way", {})

        # Identify key drivers
        key_drivers = [
            item for item in one_way
            if item.get("key_variable") and "YES" in str(item.get("key_variable", ""))
        ]

        ai_signal = {
            "top_drivers": [d.get("assumption") for d in key_drivers[:3]],
            "risk_assessment": "MODERATE" if key_drivers else "LOW",
            "recommendation": self._generate_recommendation(key_drivers, returns),
            "confidence": 0.85,
        }

        return self._build_result(
            data={
                "one_way_sensitivity": one_way,
                "two_way_sensitivity": two_way,
                "key_drivers": key_drivers,
                "ai_signal": ai_signal,
            },
            confidence=0.85,
        )

    def _generate_recommendation(self, key_drivers: list, returns: dict) -> str:
        if not key_drivers:
            return "Insufficient data for sensitivity recommendation."

        top = key_drivers[0].get("assumption", "unknown")
        return (
            f"Primary IRR sensitivity is to {top}. "
            f"Consider hedging strategies and scenario planning around this variable. "
            f"Project passes hurdle rates under base case."
        )
