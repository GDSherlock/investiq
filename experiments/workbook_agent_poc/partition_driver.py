"""Stateless Azure Responses driver for bounded workbook partitions."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import time
from typing import Any, Callable, Protocol

from openai import OpenAI, OpenAIError

from partition_contract import (
    PARTITION_SYSTEM_PROMPT,
    PartitionResultIssue,
    RECONCILIATION_SYSTEM_PROMPT,
    SUBMIT_PARTITION_TOOL,
    SUBMIT_RECONCILIATION_TOOL,
    serialize_partition_envelope,
    validate_partition_tool_arguments,
)
from partition_planner import WorkbookPartition


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ToolCallInspection:
    arguments: dict[str, Any] | None
    call_id: str | None
    has_function_calls: bool


class PartitionDriverError(RuntimeError):
    code = "partition_driver_error"

    def __init__(self, message: str, *, request_id: str | None = None):
        self.request_id = request_id
        super().__init__(message)


class PartitionContextLimitError(PartitionDriverError):
    code = "context_length_exceeded"


class PartitionAuthenticationError(PartitionDriverError):
    code = "azure_authentication_failed"


class PartitionTransientError(PartitionDriverError):
    code = "azure_transient_failure"


class PartitionStructuredOutputError(PartitionDriverError):
    code = "partition_structured_output_invalid"


class PartitionDriver(Protocol):
    call_count: int
    max_calls_per_operation: int

    def extract(
        self,
        partition: WorkbookPartition,
        envelope: dict[str, Any],
    ) -> dict[str, Any]: ...

    def resolve_conflict(
        self,
        conflict_envelope: dict[str, Any],
    ) -> dict[str, Any] | None: ...


def _flatten_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool["function"]
    return {
        "type": tool["type"],
        "name": function["name"],
        "description": function["description"],
        "parameters": function["parameters"],
    }


def _error_code(exc: OpenAIError) -> str | None:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        nested = body.get("error") if isinstance(body.get("error"), dict) else body
        nested_code = nested.get("code")
        if isinstance(nested_code, str):
            return nested_code
    return None


class AzurePartitionDriver:
    def __init__(
        self,
        *,
        max_retries_per_call: int = 2,
        sleeper: Callable[[float], None] = time.sleep,
        client: Any | None = None,
    ):
        self._client = client or OpenAI(
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/",
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            max_retries=0,
        )
        self._deployment = os.getenv(
            "AZURE_OPENAI_GPT_DEPLOYMENT",
            "gpt-5.4-mini",
        )
        self._max_output_tokens = int(
            os.getenv("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "16384")
        )
        self._reasoning_effort = os.getenv(
            "AZURE_OPENAI_REASONING_EFFORT",
            "medium",
        )
        self._max_retries_per_call = max_retries_per_call
        self._sleeper = sleeper
        self.max_calls_per_operation = 2 * (max_retries_per_call + 1)
        self.call_count = 0
        self.usage_prompt = 0
        self.usage_completion = 0
        self.request_ids: list[str] = []

    def extract(
        self,
        partition: WorkbookPartition,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        payload = serialize_partition_envelope(envelope).decode("utf-8")
        result = self._structured_operation(
            initial_input=[{"role": "user", "content": payload}],
            instructions=PARTITION_SYSTEM_PROMPT,
            tool=SUBMIT_PARTITION_TOOL,
            expected_tool_name="submit_partition_result",
            required_fields={
                "workbook_version",
                "partition_id",
                "sheet_name",
                "primary_range",
                "result",
            },
            operation_id=partition.partition_id,
            payload_validator=validate_partition_tool_arguments,
        )
        return result

    def resolve_conflict(
        self,
        conflict_envelope: dict[str, Any],
    ) -> dict[str, Any] | None:
        conflict_id = str(conflict_envelope.get("conflict_id", "unknown"))
        payload = json.dumps(
            conflict_envelope,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        result = self._structured_operation(
            initial_input=[{"role": "user", "content": payload}],
            instructions=RECONCILIATION_SYSTEM_PROMPT,
            tool=SUBMIT_RECONCILIATION_TOOL,
            expected_tool_name="submit_partition_reconciliation",
            required_fields={
                "conflict_id",
                "resolution",
                "selected_bucket",
                "reasoning_summary",
            },
            operation_id=conflict_id,
        )
        if result.get("resolution") == "review_required":
            return None
        if result.get("resolution") != "select":
            raise PartitionStructuredOutputError(
                "Reconciliation returned an unsupported resolution."
            )
        return result

    def _structured_operation(
        self,
        *,
        initial_input: list[dict[str, Any]],
        instructions: str,
        tool: dict[str, Any],
        expected_tool_name: str,
        required_fields: set[str],
        operation_id: str,
        payload_validator: (
            Callable[[dict[str, Any]], PartitionResultIssue | None] | None
        ) = None,
    ) -> dict[str, Any]:
        previous_response_id: str | None = None
        next_input = initial_input
        for structured_attempt in range(2):
            kwargs: dict[str, Any] = {
                "model": self._deployment,
                "input": next_input,
                "instructions": instructions,
                "tools": [_flatten_tool(tool)],
                "tool_choice": {
                    "type": "function",
                    "name": expected_tool_name,
                },
                "parallel_tool_calls": False,
                "max_output_tokens": self._max_output_tokens,
                "reasoning": {"effort": self._reasoning_effort},
            }
            if previous_response_id is not None:
                kwargs["previous_response_id"] = previous_response_id
            response = self._call_with_retry(kwargs, operation_id=operation_id)
            inspection = self._inspect_tool_result(
                response,
                expected_tool_name=expected_tool_name,
                required_fields=required_fields,
            )
            parsed = inspection.arguments
            issue = (
                payload_validator(parsed)
                if parsed is not None and payload_validator is not None
                else None
            )
            if parsed is not None and issue is None:
                return parsed
            validation_code = (
                issue.code
                if issue is not None
                else "partition_tool_call_invalid"
            )
            logger.warning(
                "partition_structured_output_rejected operation_id=%s "
                "validation_code=%s structured_attempt=%s",
                operation_id,
                validation_code,
                structured_attempt,
            )
            if structured_attempt == 0:
                if (
                    inspection.has_function_calls
                    and inspection.call_id is None
                ):
                    raise PartitionStructuredOutputError(
                        "Azure response contained an unacknowledgeable "
                        "function call."
                    )
                previous_response_id = response.id
                repair_instruction = (
                    issue.repair_instruction
                    if issue is not None
                    else (
                        f"Return exactly one {expected_tool_name} function call "
                        "with every required field."
                    )
                )
                if inspection.call_id is not None:
                    next_input = [{
                        "type": "function_call_output",
                        "call_id": inspection.call_id,
                        "output": json.dumps(
                            {
                                "accepted": False,
                                "validation_code": validation_code,
                                "repair_instruction": repair_instruction,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }]
                else:
                    next_input = [{
                        "role": "user",
                        "content": repair_instruction,
                    }]
        raise PartitionStructuredOutputError(
            "Azure response did not contain a valid structured partition result."
        )

    def _call_with_retry(
        self,
        kwargs: dict[str, Any],
        *,
        operation_id: str,
    ) -> Any:
        for attempt in range(self._max_retries_per_call + 1):
            self.call_count += 1
            try:
                response = self._client.responses.create(**kwargs)
            except OpenAIError as exc:
                status_code = getattr(exc, "status_code", None)
                request_id = getattr(exc, "request_id", None)
                code = _error_code(exc)
                logger.warning(
                    "partition_call_failed operation_id=%s status=%s code=%s request_id=%s attempt=%s",
                    operation_id,
                    status_code,
                    code,
                    request_id,
                    attempt,
                )
                if code == "context_length_exceeded":
                    raise PartitionContextLimitError(
                        "Azure rejected the partition context length.",
                        request_id=request_id,
                    ) from exc
                if status_code in {401, 403}:
                    raise PartitionAuthenticationError(
                        "Azure authentication or authorization failed.",
                        request_id=request_id,
                    ) from exc
                retryable = status_code is None or status_code == 429 or (
                    isinstance(status_code, int) and status_code >= 500
                )
                if retryable and attempt < self._max_retries_per_call:
                    self._sleeper(min(2 ** attempt, 4))
                    continue
                if retryable:
                    raise PartitionTransientError(
                        "Azure transient retry budget was exhausted.",
                        request_id=request_id,
                    ) from exc
                raise PartitionDriverError(
                    "Azure Responses API rejected the partition request.",
                    request_id=request_id,
                ) from exc

            self._record_response(response)
            logger.info(
                "partition_call_completed operation_id=%s request_id=%s",
                operation_id,
                getattr(response, "_request_id", None),
            )
            return response
        raise PartitionTransientError("Azure retry loop ended unexpectedly.")

    def _record_response(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage_prompt += getattr(usage, "input_tokens", 0) or 0
            self.usage_completion += getattr(usage, "output_tokens", 0) or 0
        request_id = getattr(response, "_request_id", None)
        if isinstance(request_id, str) and request_id:
            self.request_ids.append(request_id)

    @staticmethod
    def _inspect_tool_result(
        response: Any,
        *,
        expected_tool_name: str,
        required_fields: set[str],
    ) -> _ToolCallInspection:
        function_calls = [
            item
            for item in getattr(response, "output", [])
            if getattr(item, "type", None) == "function_call"
        ]
        expected_calls = [
            item
            for item in function_calls
            if getattr(item, "name", None) == expected_tool_name
        ]
        if len(function_calls) != 1 or len(expected_calls) != 1:
            return _ToolCallInspection(
                arguments=None,
                call_id=None,
                has_function_calls=bool(function_calls),
            )

        call = expected_calls[0]
        raw_call_id = getattr(call, "call_id", None)
        call_id = (
            raw_call_id.strip()
            if isinstance(raw_call_id, str) and raw_call_id.strip()
            else None
        )
        try:
            parsed = json.loads(call.arguments or "{}")
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if not isinstance(parsed, dict) or not required_fields <= set(parsed):
            parsed = None
        return _ToolCallInspection(
            arguments=parsed,
            call_id=call_id,
            has_function_calls=True,
        )


__all__ = [
    "AzurePartitionDriver",
    "PartitionAuthenticationError",
    "PartitionContextLimitError",
    "PartitionDriver",
    "PartitionDriverError",
    "PartitionStructuredOutputError",
    "PartitionTransientError",
]
