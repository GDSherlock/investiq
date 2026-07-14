"""
EXPERIMENTAL — isolated. Backend-owned function-calling control loop with coverage
enforcement and hard caps. Drivers (mock / Azure) implement next_tool_call + observe.

The loop:
  * validates tool name + arguments before executing
  * executes local tools INSIDE the backend
  * refuses submit_extraction_result until the coverage gate passes (loop continues)
  * enforces hard caps: iterations, tool calls, deadline, repeated-identical calls
  * records an append-only trace + backend-tracked coverage
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from workbook_tools import (
    DEFAULT_CHUNK_PAYLOAD_BYTES,
    MAX_OBSERVATION_PAYLOAD_BYTES,
    WorkbookToolset,
    ToolError,
)
from coverage_gate import CoverageTracker, HardCaps
from extraction_contract import TOOL_SCHEMAS, SYSTEM_PROMPT


def build_dispatch(tools: WorkbookToolset) -> dict[str, Callable[..., Any]]:
    return {
        "list_sheets": lambda **kw: tools.list_sheets(),
        "get_workbook_metadata": lambda **kw: tools.get_workbook_metadata(),
        "inspect_sheet": lambda **kw: tools.inspect_sheet(kw["sheet_name"]),
        "read_range": lambda **kw: tools.read_range(kw["sheet_name"], kw["cell_range"]),
        "get_cell": lambda **kw: tools.get_cell(kw["sheet_name"], kw["cell_reference"]),
        "search_cells": lambda **kw: tools.search_cells(kw["query"], in_formulas=kw.get("in_formulas", False)),
        "get_data_validations": lambda **kw: tools.get_data_validations(kw["sheet_name"]),
        "get_formulas": lambda **kw: tools.get_formulas(kw["sheet_name"], kw.get("cell_range")),
        "submit_extraction_result": lambda **kw: tools.submit_extraction_result(kw["result"]),
    }


def _preview(result: Any, limit: int = 200) -> tuple[str, bool]:
    rendered = json.dumps(result, default=str, ensure_ascii=False)
    truncated = len(rendered) > limit
    preview = rendered if not truncated else rendered[:limit] + "…"
    return preview, truncated


class ObservationPayloadTooLarge(ValueError):
    def __init__(self, serialized_bytes: int, max_bytes: int):
        self.serialized_bytes = serialized_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"Observation payload is {serialized_bytes} bytes; limit is {max_bytes}."
        )


def serialize_observation_payload(
    result: Any,
    *,
    max_bytes: int = MAX_OBSERVATION_PAYLOAD_BYTES,
    raise_on_too_large: bool = False,
) -> str:
    """Serialize one whole observation or return one whole structured error."""
    payload = json.dumps(
        result,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    serialized_bytes = len(payload.encode("utf-8"))
    if serialized_bytes <= max_bytes:
        return payload
    if raise_on_too_large:
        raise ObservationPayloadTooLarge(serialized_bytes, max_bytes)
    error = {
        "error": {
            "code": "payload_too_large",
            "message": "Tool result exceeded the complete observation payload limit.",
            "serialized_bytes": serialized_bytes,
            "max_bytes": max_bytes,
        }
    }
    return json.dumps(error, ensure_ascii=False, separators=(",", ":"))


def _observe_many(model, name: str, args: dict[str, Any], results: list[Any]) -> None:
    if hasattr(model, "observe_many"):
        model.observe_many(name, args, results)
        return
    for result in results:
        model.observe(name, args, result)


def _read_all_chunks(
    tools: WorkbookToolset,
    args: dict[str, Any],
    *,
    budget: int,
    max_internal_chunks: int,
    on_internal_fetch: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    first = tools.read_range(
        args["sheet_name"],
        args["cell_range"],
        max_serialized_bytes=budget,
    )
    required_internal = max(0, int(first.get("chunk_count", 1)) - 1)
    if required_internal > max_internal_chunks:
        raise ToolError(
            "internal_chunk_limit_exceeded",
            f"Range requires {required_internal} internal continuation fetches; "
            f"the remaining runtime limit is {max_internal_chunks}.",
        )
    chunks = [first]
    seen = {first.get("chunk_id")}
    while chunks[-1].get("has_more"):
        token = chunks[-1].get("continuation_token")
        if not token:
            raise ToolError(
                "missing_continuation_token",
                "Backend chunk state indicated more data without a continuation token.",
            )
        following = tools.read_range(
            args["sheet_name"],
            args["cell_range"],
            continuation_token=token,
            max_serialized_bytes=budget,
        )
        if on_internal_fetch:
            on_internal_fetch()
        if following.get("chunk_id") in seen:
            raise ToolError(
                "repeated_continuation_chunk",
                "Continuation token returned a chunk already seen by this runtime request.",
            )
        chunks.append(following)
        seen.add(following.get("chunk_id"))
    return chunks


def _with_serialized_bytes(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    serialized_bytes = -1
    while result.get("serialized_bytes") != serialized_bytes:
        result["serialized_bytes"] = serialized_bytes
        serialized_bytes = len(json.dumps(
            result, default=str, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"))
    result["serialized_bytes"] = serialized_bytes
    return result


def _public_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """Remove backend-only cursor state before a chunk enters model context."""
    public = dict(chunk)
    public.pop("continuation_token", None)
    public["continuation_managed_by_runtime"] = True
    return _with_serialized_bytes(public)


def _serialized_size(result: Any) -> int:
    return len(json.dumps(
        result, default=str, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8"))


def _already_completed_result(
    cov: CoverageTracker, name: str, args: dict[str, Any]
) -> dict[str, Any] | None:
    completed = (
        (name == "get_workbook_metadata" and cov.metadata_inspected)
        or (name == "list_sheets" and cov.list_sheets_completed)
        or (
            name == "inspect_sheet"
            and args.get("sheet_name") in cov.inspected
        )
    )
    if not completed:
        return None
    return {
        "tool_name": name,
        "sheet_name": args.get("sheet_name"),
        "already_completed": True,
        "coverage_status": cov.coverage_status(),
    }


def run_loop(model, tools: WorkbookToolset, *, caps: HardCaps | None = None, verbose: bool = False) -> dict[str, Any]:
    caps = caps or HardCaps()
    dispatch = build_dispatch(tools)
    cov = CoverageTracker(tools)
    trace: list[dict] = []
    started = time.monotonic()
    final_extraction: dict[str, Any] | None = None
    stop_reason = "unknown"

    for i in range(caps.max_iterations):
        if time.monotonic() - started > caps.deadline_seconds:
            stop_reason = "deadline_exceeded"; break
        if cov.logical_model_tool_calls >= caps.max_tool_calls:
            stop_reason = "max_tool_calls"; break
        if cov.max_repeat_count() >= caps.max_repeated_identical:
            stop_reason = "repeated_identical_calls"; break

        remaining_logical_calls = caps.max_tool_calls - cov.logical_model_tool_calls
        if remaining_logical_calls <= caps.reserved_submit_call:
            if not cov.submission_allowed():
                stop_reason = "max_tool_calls_reserved_for_submit"; break
            if hasattr(model, "require_submission"):
                model.require_submission()

        if hasattr(model, "set_submission_allowed"):
            model.set_submission_allowed(cov.submission_allowed())

        call = model.next_tool_call(trace)
        if call is None:
            stop_reason = "model_returned_no_tool_call"; break

        name, args = call.get("name"), call.get("arguments", {}) or {}
        cov.record_logical_call(name, args if name != "submit_extraction_result" else {
            "result": "<omitted>"
        })

        if name not in dispatch:
            result = {"error": {"code": "unknown_tool", "message": f"{name!r} is not a registered tool"}}
        elif name == "submit_extraction_result":
            # backend coverage GATE — the model does not get to declare completion.
            ok, gate = cov.submission_gate()
            if ok:
                result = dispatch[name](**args)
                preview, preview_truncated = _preview(result)
                trace.append({"iter": i, "tool": name, "arguments": "<result omitted>",
                              "result_preview": preview, "result_truncated": preview_truncated,
                              "coverage_gate": "passed"})
                if verbose:
                    print(f"  [{i}] submit -> ACCEPTED ({preview})")
                model.observe(name, args, result)
                cov.record_driver_observation(_serialized_size(result))
                final_extraction = args.get("result", {})
                stop_reason = "submitted"; break
            else:
                result = gate
                preview, preview_truncated = _preview(result)
                trace.append({"iter": i, "tool": name, "arguments": "<result omitted>",
                              "result_preview": preview, "result_truncated": preview_truncated,
                              "coverage_gate": "REJECTED"})
                if verbose:
                    print(f"  [{i}] submit -> REJECTED (missing {gate['coverage']['missing_sheets']})")
                model.observe(name, args, result)
                cov.record_driver_observation(_serialized_size(result))
                continue
        else:
            if name == "read_range":
                if args.get("continuation_token"):
                    result = {"error": {
                        "code": "runtime_managed_continuation",
                        "message": "Continuation tokens are backend-only; call read_range once.",
                    }}
                    _observe_many(model, name, args, [result])
                    cov.record_driver_observation(_serialized_size(result))
                    trace.append({"iter": i, "tool": name, "arguments": args,
                                  "result_preview": _preview(result)[0],
                                  "result_truncated": False})
                    continue
                if cov.is_range_observed(args.get("sheet_name"), args.get("cell_range")):
                    cov.record_duplicate_range_request()
                    result = {
                        "sheet_name": args.get("sheet_name"),
                        "requested_range": str(args.get("cell_range", "")).upper(),
                        "already_observed": True,
                        "observation_complete": True,
                        "submission_allowed": cov.submission_allowed(),
                        "continuation_managed_by_runtime": True,
                        "coverage_status": cov.coverage_status(),
                    }
                    _observe_many(model, name, args, [result])
                    cov.record_driver_observation(_serialized_size(result))
                    trace.append({"iter": i, "tool": name, "arguments": args,
                                  "duplicate_range_request": True,
                                  "result_preview": _preview(result)[0],
                                  "result_truncated": False})
                    if result["submission_allowed"] and hasattr(model, "require_submission"):
                        model.require_submission()
                    continue
                budget = min(
                    DEFAULT_CHUNK_PAYLOAD_BYTES,
                    int(getattr(model, "observation_payload_budget", DEFAULT_CHUNK_PAYLOAD_BYTES)),
                )
                try:
                    while True:
                        remaining_internal = (
                            caps.max_internal_chunks_per_run - cov.internal_chunk_fetches
                        )
                        chunks = _read_all_chunks(
                            tools,
                            args,
                            budget=budget,
                            max_internal_chunks=min(
                                caps.max_internal_chunks_per_request,
                                max(0, remaining_internal),
                            ),
                            on_internal_fetch=cov.record_internal_chunk_fetch,
                        )
                        public_chunks = [_public_chunk(chunk) for chunk in chunks]
                        try:
                            driver_limit = int(getattr(
                                model,
                                "max_observation_bytes",
                                MAX_OBSERVATION_PAYLOAD_BYTES,
                            ))
                            for chunk in public_chunks:
                                serialize_observation_payload(
                                    chunk,
                                    max_bytes=driver_limit,
                                    raise_on_too_large=True,
                                )
                            break
                        except ObservationPayloadTooLarge as exc:
                            cov.record_payload_retry()
                            smaller = max(1_000, min(budget - 512, exc.max_bytes - 512))
                            if smaller >= budget:
                                raise
                            budget = smaller
                    payload_bytes = sum(_serialized_size(chunk) for chunk in public_chunks)
                    if cov.observed_bytes + payload_bytes > caps.max_observed_bytes_per_run:
                        raise ToolError(
                            "observed_bytes_limit_exceeded",
                            f"Delivering this range would exceed max_observed_bytes_per_run="
                            f"{caps.max_observed_bytes_per_run}.",
                        )
                    chunk_args_list = []
                    for chunk_index, chunk in enumerate(chunks):
                        chunk_args = dict(args)
                        if chunk_index:
                            chunk_args["continuation_token"] = chunks[chunk_index - 1][
                                "continuation_token"
                            ]
                        chunk_args_list.append(chunk_args)
                        cov.record_execution(name, chunk_args, chunk)
                    _observe_many(model, name, args, public_chunks)
                    for chunk_index, (chunk_args, chunk, public_chunk) in enumerate(
                        zip(chunk_args_list, chunks, public_chunks)
                    ):
                        cov.record_observation(name, chunk_args, public_chunk)
                        cov.record_driver_observation(_serialized_size(public_chunk))
                        preview, preview_truncated = _preview(public_chunk)
                        trace.append({
                            "iter": i,
                            "tool": name,
                            "arguments": chunk_args,
                            "request_id": chunk.get("request_id"),
                            "chunk_id": chunk.get("chunk_id"),
                            "returned_range": chunk.get("returned_range"),
                            "serialized_bytes": chunk.get("serialized_bytes"),
                            "auto_pulled": chunk_index > 0,
                            "result_preview": preview,
                            "result_truncated": preview_truncated,
                        })
                    request_status = {
                        "request_id": chunks[0].get("request_id"),
                        "sheet_name": chunks[0].get("sheet_name"),
                        "requested_range": chunks[0].get("requested_range"),
                        "chunk_count": len(chunks),
                        "executed_chunk_count": len(chunks),
                        "observed_chunk_count": len(chunks),
                        "observation_complete": all(
                            chunk.get("is_complete") is True for chunk in public_chunks
                        ),
                        "submission_allowed": cov.submission_allowed(),
                        "continuation_managed_by_runtime": True,
                    }
                    request_telemetry = cov.request_telemetry(
                        request_status["request_id"]
                    )
                    if request_telemetry is not None:
                        request_status.update({
                            "chunk_count": request_telemetry["chunk_count"],
                            "executed_chunk_count": request_telemetry["executed_chunk_count"],
                            "observed_chunk_count": request_telemetry["observed_chunk_count"],
                            "missing_chunk_indexes": request_telemetry["missing_chunk_indexes"],
                            "duplicate_chunk_indexes": request_telemetry["duplicate_chunk_indexes"],
                            "total_serialized_bytes": request_telemetry["total_serialized_bytes"],
                            "observation_complete": request_telemetry["coverage_complete"],
                        })
                    request_status.update(cov.coverage_status())
                    if hasattr(model, "append_runtime_status"):
                        model.append_runtime_status(request_status)
                    if request_status["submission_allowed"] and hasattr(model, "require_submission"):
                        model.require_submission()
                    if verbose:
                        print(
                            f"  [{i}] read_range({args}) -> observed {len(chunks)} complete chunks"
                        )
                except ToolError as e:
                    result = e.as_result()
                    cov.record_execution(name, args, result)
                    preview, preview_truncated = _preview(result)
                    trace.append({"iter": i, "tool": name, "arguments": args,
                                  "result_preview": preview,
                                  "result_truncated": preview_truncated})
                    _observe_many(model, name, args, [result])
                    cov.record_driver_observation(_serialized_size(result))
                continue
            completed_result = _already_completed_result(cov, name, args)
            try:
                result = (
                    completed_result
                    if completed_result is not None
                    else dispatch[name](**args)
                )
            except ToolError as e:
                result = e.as_result()
            except TypeError as e:
                result = {"error": {"code": "bad_arguments", "message": str(e)}}
            except Exception as e:
                result = {"error": {"code": "tool_exception", "message": f"{type(e).__name__}: {e}"}}
            cov.record_execution(name, args, result)
            preview, preview_truncated = _preview(result)
            trace.append({"iter": i, "tool": name, "arguments": args,
                          "result_preview": preview, "result_truncated": preview_truncated})
            if verbose:
                print(f"  [{i}] {name}({args}) -> {preview}")
            _observe_many(model, name, args, [result])
            cov.record_observation(name, args, result)
            cov.record_driver_observation(_serialized_size(result))
            if (
                name in {"get_workbook_metadata", "list_sheets", "inspect_sheet"}
                and hasattr(model, "append_runtime_status")
            ):
                model.append_runtime_status(cov.coverage_status())
    else:
        stop_reason = "max_iterations"

    return {
        "final_extraction": final_extraction or {},
        "submitted": final_extraction is not None,
        "stop_reason": stop_reason,
        "coverage": cov.coverage_summary(),
        "trace": trace,
        "iterations": len(trace),
    }


# --------------------------------------------------------------------------
# Real Azure OpenAI driver — gated behind --live in run_test_suite.
# --------------------------------------------------------------------------
class AzureDriver:
    max_observation_bytes = MAX_OBSERVATION_PAYLOAD_BYTES
    observation_payload_budget = DEFAULT_CHUNK_PAYLOAD_BYTES

    def __init__(self, system_prompt: str = SYSTEM_PROMPT):
        from openai import OpenAI

        self._client = OpenAI(
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/",
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
        )
        self._deployment = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-5.4-mini")
        self._system_prompt = system_prompt
        self._previous_response_id: str | None = None
        self._next_input: list[dict] = [
            {"role": "user", "content": "Begin workbook exploration using the available tools."}
        ]
        self._pending_id: str | None = None
        self._force_submit = False
        self._submission_allowed = False
        self.usage_prompt = 0
        self.usage_completion = 0

    def next_tool_call(self, trace):
        # Retry once with a nudge if the model replies without a tool call, else end.
        for attempt in range(2):
            tool_choice: str | dict[str, str] = "auto"
            if self._force_submit:
                tool_choice = {"type": "function", "name": "submit_extraction_result"}
            resp = self._client.responses.create(
                model=self._deployment,
                input=self._next_input,
                instructions=self._system_prompt,
                previous_response_id=self._previous_response_id,
                tools=[
                    {
                        "type": tool["type"],
                        "name": tool["function"]["name"],
                        "description": tool["function"]["description"],
                        "parameters": tool["function"]["parameters"],
                    }
                    for tool in TOOL_SCHEMAS
                    if (
                        tool["function"]["name"] != "submit_extraction_result"
                        or self._submission_allowed
                    )
                ],
                tool_choice=tool_choice,
                # The loop handles one tool call per turn and returns exactly one
                # function_call_output; forcing sequential calls keeps the
                # previous_response_id threading valid (otherwise the Responses API
                # rejects the next turn: "No tool output found for function call ...").
                parallel_tool_calls=False,
            )
            if getattr(resp, "usage", None):
                self.usage_prompt += getattr(resp.usage, "input_tokens", 0) or 0
                self.usage_completion += getattr(resp.usage, "output_tokens", 0) or 0
            self._previous_response_id = resp.id
            tool_calls = [item for item in resp.output if item.type == "function_call"]
            if tool_calls:
                tc = tool_calls[0]
                self._pending_id = tc.call_id
                try:
                    args = json.loads(tc.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                self._force_submit = False
                return {"name": tc.name, "arguments": args}
            if attempt == 0:
                self._next_input = [{"role": "user", "content":
                    "Continue exploring with the tools. When every sheet has been inspected, "
                    "call submit_extraction_result."}]
        return None

    def observe(self, name, args, result):
        self.observe_many(name, args, [result])

    def observe_many(self, name, args, results):
        serialized = [
            serialize_observation_payload(
                result,
                max_bytes=self.max_observation_bytes,
                raise_on_too_large=(name == "read_range"),
            )
            for result in results
        ]
        self._next_input = [{
            "type": "function_call_output",
            "call_id": self._pending_id,
            "output": serialized[0],
        }]
        # A Responses function call has exactly one call_id/output. Runtime-pulled
        # continuation chunks therefore travel as complete subsequent input items
        # in the same turn instead of reusing the call_id or waiting for the model.
        self._next_input.extend(
            {"role": "user", "content": payload}
            for payload in serialized[1:]
        )

    def append_runtime_status(self, status: dict[str, Any]) -> None:
        self._next_input.append({
            "role": "user",
            "content": serialize_observation_payload(
                status, max_bytes=self.max_observation_bytes, raise_on_too_large=True
            ),
        })

    def require_submission(self) -> None:
        self._submission_allowed = True
        self._force_submit = True

    def set_submission_allowed(self, allowed: bool) -> None:
        self._submission_allowed = allowed
        if not allowed:
            self._force_submit = False
