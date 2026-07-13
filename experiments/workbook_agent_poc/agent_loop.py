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

from workbook_tools import WorkbookToolset, ToolError
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
        if cov.tool_call_count >= caps.max_tool_calls:
            stop_reason = "max_tool_calls"; break
        if cov.max_repeat_count() >= caps.max_repeated_identical:
            stop_reason = "repeated_identical_calls"; break

        call = model.next_tool_call(trace)
        if call is None:
            stop_reason = "model_returned_no_tool_call"; break

        name, args = call.get("name"), call.get("arguments", {}) or {}

        if name not in dispatch:
            result = {"error": {"code": "unknown_tool", "message": f"{name!r} is not a registered tool"}}
        elif name == "submit_extraction_result":
            # backend coverage GATE — the model does not get to declare completion.
            cov.record(name, {"result": "<omitted>"}, None)
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
                continue
        else:
            try:
                result = dispatch[name](**args)
            except ToolError as e:
                result = e.as_result()
            except TypeError as e:
                result = {"error": {"code": "bad_arguments", "message": str(e)}}
            except Exception as e:
                result = {"error": {"code": "tool_exception", "message": f"{type(e).__name__}: {e}"}}
            cov.record(name, args, result)
            preview, preview_truncated = _preview(result)
            trace.append({"iter": i, "tool": name, "arguments": args,
                          "result_preview": preview, "result_truncated": preview_truncated})
            if verbose:
                print(f"  [{i}] {name}({args}) -> {preview}")
            model.observe(name, args, result)
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
        self.usage_prompt = 0
        self.usage_completion = 0

    def next_tool_call(self, trace):
        # Retry once with a nudge if the model replies without a tool call, else end.
        for attempt in range(2):
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
                ],
                tool_choice="auto",
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
                return {"name": tc.name, "arguments": args}
            if attempt == 0:
                self._next_input = [{"role": "user", "content":
                    "Continue exploring with the tools. When every sheet has been inspected, "
                    "call submit_extraction_result."}]
        return None

    def observe(self, name, args, result):
        self._next_input = [{
            "type": "function_call_output",
            "call_id": self._pending_id,
            "output": json.dumps(result, default=str, ensure_ascii=False)[:12000],
        }]
