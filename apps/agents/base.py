"""
Agent Base — shared base class for all InvestIQ agents.

Each agent:
- Has a name, description, tools, and output types
- Returns structured JSON
- Logs to audit trail
- Has a 30s timeout
"""

from abc import ABC, abstractmethod
from typing import Any
from datetime import datetime, timezone


class BaseAgent(ABC):
    """Base class for all InvestIQ agents."""

    name: str = "BaseAgent"
    description: str = ""
    tools: list[str] = []
    output_types: list[str] = []

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's task."""
        ...

    def _build_result(
        self,
        data: dict[str, Any],
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a standardized agent result."""
        return {
            "agent": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
            "confidence": confidence,
            "metadata": metadata or {},
        }
