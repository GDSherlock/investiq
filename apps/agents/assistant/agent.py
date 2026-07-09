"""
AssistantAgent — NL Q&A with model context.
Output: ConversationResponse + Sources
"""

from typing import Any
from apps.agents.base import BaseAgent


class AssistantAgent(BaseAgent):
    name = "AssistantAgent"
    description = "Natural language Q&A with financial model context"
    tools = ["vector_search", "calc_engine"]
    output_types = ["ConversationResponse", "Sources"]

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        query = context.get("query", "")
        model_data = context.get("model_data", {})

        response = self._process(query, model_data)

        return self._build_result(
            data={
                "response": response["answer"],
                "sources": response["sources"],
            },
            confidence=response["confidence"],
        )

    def _process(self, query: str, model_data: dict) -> dict:
        q = query.lower()
        cover = model_data.get("cover", {})
        returns = model_data.get("returns", {})
        metrics = returns.get("metrics", [])

        if any(w in q for w in ["irr", "return"]):
            irr_data = [m for m in metrics if "IRR" in m.get("metric", "")]
            if irr_data:
                lines = [f"{m['metric']}: Base={m.get('base_case')}" for m in irr_data]
                return {"answer": "\n".join(lines), "sources": ["Returns"], "confidence": 0.95}

        if any(w in q for w in ["npv", "net present"]):
            npv_data = [m for m in metrics if "NPV" in m.get("metric", "")]
            if npv_data:
                m = npv_data[0]
                return {"answer": f"NPV @ WACC = {m.get('base_case')} USD M", "sources": ["Returns"], "confidence": 0.95}

        if any(w in q for w in ["summary", "overview", "project"]):
            lines = [f"{k}: {v}" for k, v in cover.items()]
            return {"answer": "\n".join(lines), "sources": ["Cover"], "confidence": 0.9}

        return {
            "answer": f"I can answer questions about the financial model. Try asking about IRR, NPV, DSCR, or project summary.",
            "sources": [],
            "confidence": 0.5,
        }
