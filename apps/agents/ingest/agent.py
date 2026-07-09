"""
ModelIngestAgent — parses Excel, maps assumptions, health check.
Output: StructuredModelSchema + HealthReport
"""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from apps.agents.base import BaseAgent
from libs.tools.excel_parser import ExcelParser
from libs.tools.assumption_mapper import AssumptionMapper


class ModelIngestAgent(BaseAgent):
    name = "ModelIngestAgent"
    description = "Parses Excel financial models, maps assumptions, runs health checks"
    tools = ["excel_parser", "assumption_mapper"]
    output_types = ["StructuredModelSchema", "HealthReport"]

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        file_bytes = context.get("file_bytes")
        file_path = context.get("file_path")

        if not file_bytes and not file_path:
            return self._build_result(
                {"error": "No file provided"}, confidence=0.0
            )

        parser = ExcelParser(file_bytes=file_bytes, file_path=file_path)
        parsed_data = parser.parse_all()
        health = parser.health_check()

        # Map assumptions to categories
        assumptions = parsed_data.get("assumptions", [])
        mapped = AssumptionMapper.map_all(assumptions)

        # Detect hardcoded values
        hardcoded = AssumptionMapper.detect_hardcoded(assumptions)

        schema = {
            "sheets": parsed_data.get("sheets", []),
            "cover": parsed_data.get("cover", {}),
            "assumptions_count": len(assumptions),
            "assumptions_by_category": {},
            "hardcoded_count": len(hardcoded),
        }

        # Group by category
        categories = set(a.get("category", "OTHER") for a in mapped)
        for cat in categories:
            schema["assumptions_by_category"][cat] = len(
                [a for a in mapped if a.get("category") == cat]
            )

        return self._build_result(
            data={
                "structured_model_schema": schema,
                "health_report": health,
                "parsed_data": parsed_data,
            },
            confidence=health["health_score"] / 100.0,
            metadata={"sheets_parsed": len(parsed_data.get("sheets", []))},
        )
