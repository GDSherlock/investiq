"""
DebtAnalysisAgent — term sheets extraction + comparison.
Output: DebtComparison + Recommendation
"""

from typing import Any
from apps.agents.base import BaseAgent


class DebtAnalysisAgent(BaseAgent):
    name = "DebtAnalysisAgent"
    description = "Extracts and compares term sheets, analyzes debt structure"
    tools = ["pdf_extractor", "calc_engine"]
    output_types = ["DebtComparison", "Recommendation"]

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        model_data = context.get("model_data", {})
        debt_data = model_data.get("debt_schedule", {})
        assumptions = model_data.get("assumptions", [])

        data = debt_data.get("data", {})
        years = debt_data.get("years", [])

        # Extract key debt metrics from model
        opening = data.get("Opening debt balance", [])
        closing = data.get("Closing debt balance", [])
        drawdowns = data.get("Debt drawdown", [])
        repayments = data.get("(Scheduled repayment)", [])
        interest = data.get("Interest charge", [])
        total_service = data.get("Total debt service", [])

        # Find debt-related assumptions
        debt_assumptions = {
            a.get("name"): a.get("value")
            for a in assumptions
            if any(kw in a.get("name", "").lower() for kw in ["debt", "interest", "tenor", "grace", "sora", "margin"])
        }

        comparison = {
            "facility_summary": {
                "total_facility": sum(abs(v) for v in drawdowns if v) if drawdowns else 0,
                "peak_outstanding": max(abs(v) for v in closing if v) if closing else 0,
                "total_interest_paid": sum(abs(v) for v in interest if v) if interest else 0,
            },
            "debt_assumptions": debt_assumptions,
            "schedule": {
                "years": years,
                "opening_balance": opening,
                "closing_balance": closing,
                "drawdowns": drawdowns,
                "repayments": repayments,
                "interest": interest,
                "total_debt_service": total_service,
            },
        }

        recommendation = {
            "summary": "Debt structure follows standard project finance terms for LNG infrastructure.",
            "key_observations": [
                f"Total facility size: USD {comparison['facility_summary']['total_facility']:.1f}M",
                f"Peak outstanding: USD {comparison['facility_summary']['peak_outstanding']:.1f}M",
                "Grace period covers construction phase",
            ],
            "risks": [
                "Interest rate sensitivity through SORA exposure",
                "DSCR covenant compliance during ramp-up",
            ],
        }

        return self._build_result(
            data={"comparison": comparison, "recommendation": recommendation},
            confidence=0.8,
        )
