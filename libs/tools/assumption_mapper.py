"""
Assumption Mapper — pattern matches assumptions to financial categories.

Maps raw assumption names to categories like WACC, IRR, DSCR, etc.
"""

import re
from typing import Any

# Category patterns
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "WACC": [r"wacc", r"weighted\s+average\s+cost", r"discount\s+rate"],
    "IRR": [r"\birr\b", r"internal\s+rate\s+of\s+return", r"hurdle.*irr"],
    "DSCR": [r"\bdscr\b", r"debt\s+service\s+coverage", r"covenant"],
    "CAPEX": [r"capex", r"capital\s+expenditure", r"construction.*cost", r"epc"],
    "REVENUE": [r"revenue", r"throughput", r"fee.*\$", r"tariff", r"regasification"],
    "OPEX": [r"opex", r"operating\s+cost", r"fixed\s+opex", r"variable\s+opex", r"inflation"],
    "DEBT": [r"debt", r"loan", r"interest", r"margin.*sora", r"tenor", r"grace\s+period"],
    "EQUITY": [r"equity", r"required\s+return"],
    "TAX": [r"tax", r"capital\s+allowance", r"depreciation", r"withholding"],
    "PROJECT": [r"project\s+name", r"construction\s+period", r"operations.*year", r"project\s+life"],
    "CARBON": [r"carbon", r"co2", r"emission", r"i-rec", r"green\s+certificate"],
    "UTILISATION": [r"utilisation", r"utilization", r"capacity", r"ramp.*up"],
}


class AssumptionMapper:
    """Map raw assumptions to standardized financial categories."""

    @staticmethod
    def categorize(assumption_name: str) -> str:
        """Return the category for a given assumption name."""
        name_lower = assumption_name.lower()
        for category, patterns in CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, name_lower):
                    return category
        return "OTHER"

    @staticmethod
    def map_all(assumptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add category field to each assumption."""
        mapper = AssumptionMapper()
        for a in assumptions:
            a["category"] = mapper.categorize(a.get("name", ""))
        return assumptions

    @staticmethod
    def get_by_category(
        assumptions: list[dict[str, Any]], category: str
    ) -> list[dict[str, Any]]:
        """Filter assumptions by category."""
        mapper = AssumptionMapper()
        return [
            a for a in assumptions
            if mapper.categorize(a.get("name", "")) == category
        ]

    @staticmethod
    def detect_hardcoded(assumptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Identify assumptions that appear hardcoded (no source/reference)."""
        hardcoded = []
        for a in assumptions:
            source = a.get("source", "")
            if not source or source.lower() in ("", "none", "n/a"):
                hardcoded.append({**a, "is_hardcoded": True})
        return hardcoded
