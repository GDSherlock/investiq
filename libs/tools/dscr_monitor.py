"""
DSCR Monitor — monitors DSCR values and triggers covenant alerts.
"""

from typing import Any


class DSCRMonitor:
    """Monitor DSCR values against covenants and generate alerts."""

    def __init__(
        self,
        breach_threshold: float = 1.25,
        amber_threshold: float = 1.35,
    ):
        self.breach_threshold = breach_threshold
        self.amber_threshold = amber_threshold

    def evaluate(
        self,
        dscr_values: list[dict[str, Any]],
        years: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate DSCR values and generate alerts.

        Args:
            dscr_values: List of dicts with 'dscr' and optional 'year'.
            years: Optional year labels.

        Returns:
            Monitor result with alerts and dashboard data.
        """
        alerts = []
        statuses = []

        for i, entry in enumerate(dscr_values):
            dscr = entry.get("dscr")
            year = years[i] if years and i < len(years) else entry.get("year", i)

            if dscr is None:
                statuses.append({"year": year, "status": "N/A", "dscr": None})
                continue

            if dscr < self.breach_threshold:
                status = "BREACH"
                severity = "critical"
                alerts.append({
                    "year": year,
                    "alert_type": "DSCR_BREACH",
                    "dscr": round(dscr, 4),
                    "threshold": self.breach_threshold,
                    "severity": severity,
                    "message": f"DSCR {dscr:.2f}x below covenant minimum {self.breach_threshold}x in {year}",
                })
            elif dscr < self.amber_threshold:
                status = "AMBER"
                severity = "warning"
                alerts.append({
                    "year": year,
                    "alert_type": "DSCR_WARNING",
                    "dscr": round(dscr, 4),
                    "threshold": self.amber_threshold,
                    "severity": severity,
                    "message": f"DSCR {dscr:.2f}x approaching covenant minimum in {year}",
                })
            else:
                status = "GREEN"

            statuses.append({"year": year, "status": status, "dscr": round(dscr, 4)})

        return {
            "dashboard": statuses,
            "alerts": alerts,
            "summary": {
                "total_periods": len(dscr_values),
                "breach_count": sum(1 for s in statuses if s["status"] == "BREACH"),
                "amber_count": sum(1 for s in statuses if s["status"] == "AMBER"),
                "green_count": sum(1 for s in statuses if s["status"] == "GREEN"),
            },
        }
