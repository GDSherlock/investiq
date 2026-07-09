"""
MonitorAgent — actual vs plan + alerts.
Output: MonitorDashboard + Alerts
"""

from typing import Any
from apps.agents.base import BaseAgent


class MonitorAgent(BaseAgent):
    name = "MonitorAgent"
    description = "Monitors actual vs plan performance and generates alerts"
    tools = ["dscr_monitor", "calc_engine"]
    output_types = ["MonitorDashboard", "Alerts"]

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        model_data = context.get("model_data", {})
        returns = model_data.get("returns", {})
        pnl_data = model_data.get("pnl", {})
        debt_data = model_data.get("debt_schedule", {})

        # KPIs from returns
        kpis = {}
        for m in returns.get("metrics", []):
            kpis[m.get("metric", "")] = {
                "base": m.get("base_case"),
                "stress": m.get("stress_case"),
                "upside": m.get("upside_case"),
                "status": m.get("status"),
            }

        # DSCR monitoring
        dscr_values = debt_data.get("data", {}).get("DSCR", [])
        years = debt_data.get("years", [])

        alerts = []
        dscr_dashboard = []
        for i, val in enumerate(dscr_values):
            if val is not None and val != 0:
                year = years[i] if i < len(years) else i
                if val < 1.25:
                    alerts.append({
                        "year": year,
                        "type": "DSCR_BREACH",
                        "value": val,
                        "severity": "critical",
                    })
                elif val < 1.35:
                    alerts.append({
                        "year": year,
                        "type": "DSCR_WARNING",
                        "value": val,
                        "severity": "warning",
                    })
                dscr_dashboard.append({"year": year, "dscr": val})

        return self._build_result(
            data={
                "dashboard": {"kpis": kpis, "dscr": dscr_dashboard},
                "alerts": alerts,
            },
            confidence=0.9,
        )
