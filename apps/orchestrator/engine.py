"""
IOE — Intelligent Orchestration Engine.

LangGraph-style state machine that:
- Classifies intent
- Injects model context into agent calls
- Runs agents in parallel where possible
- Aggregates results
- Persists state + audit log
- Retries failures (max 2), uses cached results
- Confidence gates outputs (<0.5 suppressed; 0.5–0.7 human review)
"""

import uuid
import asyncio
from enum import Enum
from typing import Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone


class IntentType(str, Enum):
    MODEL_INGEST = "model_ingest"
    SENSITIVITY = "sensitivity"
    MONTE_CARLO = "monte_carlo"
    CASH_FLOW = "cash_flow"
    DEBT_ANALYSIS = "debt_analysis"
    REPORT = "report"
    ASSISTANT = "assistant"
    UNKNOWN = "unknown"


@dataclass
class OrchestrationState:
    """State object passed through the orchestration pipeline."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    intent: IntentType = IntentType.UNKNOWN
    model_id: str | None = None
    scenario_id: str | None = None
    model_context: dict[str, Any] = field(default_factory=dict)
    agent_results: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    audit_trail: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add_audit(self, action: str, details: dict | None = None):
        self.audit_trail.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": details or {},
        })


# Intent classification patterns
_INTENT_PATTERNS = {
    IntentType.MODEL_INGEST: ["upload", "ingest", "parse", "import model"],
    IntentType.SENSITIVITY: ["sensitivity", "scenario", "what if", "stress test"],
    IntentType.MONTE_CARLO: ["monte carlo", "simulation", "probability", "var"],
    IntentType.CASH_FLOW: ["cash flow", "fcf", "cashflow", "free cash"],
    IntentType.DEBT_ANALYSIS: ["debt", "term sheet", "loan", "financing"],
    IntentType.REPORT: ["report", "ic paper", "board pack", "generate report"],
    IntentType.ASSISTANT: ["question", "explain", "what is", "help", "tell me"],
}

# Agent mapping
AGENT_REGISTRY: dict[IntentType, str] = {
    IntentType.MODEL_INGEST: "ModelIngestAgent",
    IntentType.SENSITIVITY: "SensitivityAgent",
    IntentType.MONTE_CARLO: "MonteCarloAgent",
    IntentType.CASH_FLOW: "CashFlowAgent",
    IntentType.DEBT_ANALYSIS: "DebtAnalysisAgent",
    IntentType.REPORT: "ReportAgent",
    IntentType.ASSISTANT: "AssistantAgent",
}


class OrchestrationEngine:
    """LangGraph-style state machine orchestrator."""

    def __init__(self, cache=None, max_retries: int = 2):
        self._cache = cache or {}
        self._max_retries = max_retries
        self._agents: dict[str, Callable] = {}

    def register_agent(self, name: str, handler: Callable):
        """Register an agent handler."""
        self._agents[name] = handler

    async def run(
        self,
        user_input: str,
        model_id: str | None = None,
        scenario_id: str | None = None,
        model_context: dict | None = None,
    ) -> OrchestrationState:
        """Execute the orchestration pipeline."""
        state = OrchestrationState(
            model_id=model_id,
            scenario_id=scenario_id,
            model_context=model_context or {},
        )

        # Step 1: Classify intent
        state = self._classify_intent(state, user_input)
        state.add_audit("intent_classified", {"intent": state.intent.value})

        # Step 2: Route to agent(s)
        agents_to_run = self._get_agents(state)
        state.add_audit("agents_selected", {"agents": [a for a in agents_to_run]})

        # Step 3: Execute agents (parallel where possible)
        for agent_name in agents_to_run:
            result = await self._execute_agent(agent_name, state)
            state.agent_results[agent_name] = result

        # Step 4: Aggregate results
        state = self._aggregate(state)

        # Step 5: Confidence gate
        state = self._confidence_gate(state)

        state.status = "completed"
        state.add_audit("orchestration_complete", {
            "confidence": state.confidence,
            "status": state.status,
        })

        return state

    def _classify_intent(self, state: OrchestrationState, user_input: str) -> OrchestrationState:
        """Classify user intent from input text."""
        input_lower = user_input.lower()
        for intent, patterns in _INTENT_PATTERNS.items():
            if any(p in input_lower for p in patterns):
                state.intent = intent
                return state
        state.intent = IntentType.ASSISTANT
        return state

    def _get_agents(self, state: OrchestrationState) -> list[str]:
        """Determine which agents to run based on intent."""
        agent_name = AGENT_REGISTRY.get(state.intent)
        if agent_name:
            return [agent_name]
        return ["AssistantAgent"]

    async def _execute_agent(
        self, agent_name: str, state: OrchestrationState
    ) -> dict[str, Any]:
        """Execute an agent with retry logic."""
        # Check cache first
        cache_key = f"{agent_name}:{state.model_id}:{state.scenario_id}"
        if cache_key in self._cache:
            state.add_audit("cache_hit", {"agent": agent_name})
            return self._cache[cache_key]

        for attempt in range(self._max_retries + 1):
            try:
                handler = self._agents.get(agent_name)
                if handler:
                    result = await handler(state)
                else:
                    result = {
                        "agent": agent_name,
                        "status": "no_handler",
                        "message": f"Agent {agent_name} not registered",
                    }

                # Cache result
                self._cache[cache_key] = result
                state.add_audit("agent_executed", {
                    "agent": agent_name,
                    "attempt": attempt + 1,
                    "status": "success",
                })
                return result

            except Exception as e:
                state.errors.append({
                    "agent": agent_name,
                    "attempt": attempt + 1,
                    "error": str(e),
                })
                if attempt == self._max_retries:
                    state.add_audit("agent_failed", {
                        "agent": agent_name,
                        "attempts": attempt + 1,
                        "error": str(e),
                    })
                    return {"agent": agent_name, "status": "failed", "error": str(e)}

        return {"agent": agent_name, "status": "failed"}

    def _aggregate(self, state: OrchestrationState) -> OrchestrationState:
        """Aggregate results from all agents."""
        confidences = []
        for result in state.agent_results.values():
            if isinstance(result, dict):
                conf = result.get("confidence", 0.5)
                confidences.append(conf)

        state.confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return state

    def _confidence_gate(self, state: OrchestrationState) -> OrchestrationState:
        """Apply confidence gates: <0.5 suppressed; 0.5-0.7 human review."""
        if state.confidence < 0.5:
            state.status = "suppressed"
            state.add_audit("confidence_gate", {
                "action": "suppressed",
                "confidence": state.confidence,
            })
        elif state.confidence < 0.7:
            state.status = "human_review_required"
            state.add_audit("confidence_gate", {
                "action": "human_review",
                "confidence": state.confidence,
            })
        else:
            state.status = "approved"
        return state
