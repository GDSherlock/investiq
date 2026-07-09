"""
MonteCarloAgent — distributions + correlation + VaR.
Output: MCResult + DistributionHistogram
"""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from apps.agents.base import BaseAgent
from libs.calc_engine.monte_carlo import monte_carlo_simulation


class MonteCarloAgent(BaseAgent):
    name = "MonteCarloAgent"
    description = "Runs Monte Carlo simulations with correlated distributions"
    tools = ["mc_engine", "calc_engine"]
    output_types = ["MCResult", "DistributionHistogram"]

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        base_assumptions = context.get("base_assumptions", {})
        volatilities = context.get("volatilities", {})
        n_simulations = context.get("n_simulations", 10000)
        distribution = context.get("distribution", "normal")
        correlation_matrix = context.get("correlation_matrix")

        if not base_assumptions:
            return self._build_result(
                {"error": "No base assumptions provided"}, confidence=0.0
            )

        mc_result = monte_carlo_simulation(
            base_assumptions=base_assumptions,
            volatilities=volatilities,
            correlation_matrix=correlation_matrix,
            n_simulations=n_simulations,
            distribution=distribution,
        )

        return self._build_result(
            data={
                "mc_result": mc_result.get("result", {}),
                "histogram": mc_result.get("histogram", []),
                "formula_used": mc_result.get("formula_used"),
            },
            confidence=mc_result.get("confidence", 0.8),
        )
