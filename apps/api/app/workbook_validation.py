"""Experimental adapter from FastAPI uploads to the workbook-agent PoC.

This module deliberately performs no persistence, vectorization, legacy parsing,
or health scoring. It exists only for validation in the Modelextratcion_test worktree.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable
from zipfile import BadZipFile

from openai import OpenAIError
from openpyxl.utils.exceptions import InvalidFileException


_ROOT = Path(__file__).resolve().parents[3]
_POC_DIR = _ROOT / "experiments" / "workbook_agent_poc"
if str(_POC_DIR) not in sys.path:
    sys.path.insert(0, str(_POC_DIR))

from agent_loop import AzureDriver, run_loop  # noqa: E402
from coverage_gate import HardCaps  # noqa: E402
from partition_driver import AzurePartitionDriver  # noqa: E402
from partition_pipeline import (  # noqa: E402
    PartitionPipelineError,
    run_partitioned_extraction,
)
from roles import family as role_family  # noqa: E402
from validator import validate_extraction  # noqa: E402
from workbook_tools import WorkbookToolset  # noqa: E402
from time_series import materialize_financial_series  # noqa: E402


class InvalidWorkbookError(Exception):
    """The upload is not a readable OOXML workbook."""


class AzureConfigurationError(Exception):
    """Required Azure OpenAI settings are unavailable."""


class AzureResponsesError(Exception):
    """The Azure Responses API failed before a result was assembled."""


class WorkbookValidationError(Exception):
    """A local workbook-agent or deterministic validation step failed."""


def _validation_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "candidate_count": len(results),
        "validated": 0,
        "validated_with_warning": 0,
        "validated_null": 0,
        "reclassified": 0,
        "review_required": 0,
        "rejected": 0,
    }
    for result in results:
        status = result.get("validation_status")
        if status in summary:
            summary[status] += 1
    return summary


def _validation_warnings(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for result in results:
        for message in result.get("validation_warnings", []) or []:
            warnings.append({
                "code": "CANDIDATE_VALIDATION_WARNING",
                "message": str(message),
                "context": {
                    "candidate_id": result.get("candidate_id"),
                    "series_id": result.get("series_id"),
                },
            })
    return warnings


def _partitioned_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    configured = os.getenv(
        "WORKBOOK_AGENT_PARTITIONED_EXTRACTION_ENABLED",
        "true",
    )
    return configured.strip().lower() not in {"0", "false", "no", "off"}


def _driver_meta(driver: Any, *, partitioned: bool) -> dict[str, Any]:
    return {
        "api": "responses",
        "deployment": getattr(
            driver,
            "_deployment",
            os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-5.4-mini"),
        ),
        "prompt_tokens": getattr(driver, "usage_prompt", 0),
        "completion_tokens": getattr(driver, "usage_completion", 0),
        "partitioned": partitioned,
        "azure_call_count": getattr(driver, "call_count", 0),
        "request_ids": list(getattr(driver, "request_ids", [])),
    }


def run_workbook_validation(
    file_bytes: bytes,
    filename: str,
    driver_factory: Callable[[], Any] = AzureDriver,
    *,
    partitioned: bool | None = None,
    partition_driver_factory: Callable[[], Any] = AzurePartitionDriver,
) -> dict[str, Any]:
    """Run controlled workbook exploration and deterministic validation synchronously."""
    started = time.monotonic()
    use_partitioned = _partitioned_enabled(partitioned)

    with tempfile.TemporaryDirectory(prefix="investiq-workbook-") as temp_dir:
        workbook_path = Path(temp_dir) / "uploaded.xlsx"
        workbook_path.write_bytes(file_bytes)

        try:
            tools = WorkbookToolset(file_path=str(workbook_path))
        except (BadZipFile, InvalidFileException, EOFError, ValueError, OSError) as exc:
            raise InvalidWorkbookError("The upload is not a readable OOXML workbook.") from exc

        try:
            driver = (
                partition_driver_factory()
                if use_partitioned
                else driver_factory()
            )
        except KeyError as exc:
            raise AzureConfigurationError("Required Azure OpenAI configuration is missing.") from exc
        except OpenAIError as exc:
            raise AzureResponsesError("Azure Responses API initialization failed.") from exc

        try:
            if use_partitioned:
                run = run_partitioned_extraction(driver, tools)
            else:
                run = run_loop(driver, tools, caps=HardCaps())
            series_outcome = materialize_financial_series(tools, run["final_extraction"])
            validation_results = validate_extraction(
                tools,
                run["final_extraction"],
                financial_series_outcome=series_outcome,
            )
        except PartitionPipelineError as exc:
            if exc.azure_failure:
                raise AzureResponsesError(
                    "Azure Responses API execution failed."
                ) from exc
            raise WorkbookValidationError(
                "Workbook-agent validation failed."
            ) from exc
        except OpenAIError as exc:
            raise AzureResponsesError("Azure Responses API execution failed.") from exc
        except Exception as exc:
            raise WorkbookValidationError("Workbook-agent validation failed.") from exc

        errors: list[dict[str, Any]] = []
        if not run["submitted"]:
            errors.append({
                "code": "AGENT_INCOMPLETE",
                "message": f"Workbook agent stopped before submission: {run['stop_reason']}",
            })

        trace = run["trace"]
        return {
            "endpoint_mode": "experimental_workbook_agent_validation",
            "filename": filename,
            "runtime_seconds": round(time.monotonic() - started, 2),
            "driver_meta": _driver_meta(driver, partitioned=use_partitioned),
            "submitted": run["submitted"],
            "stop_reason": run["stop_reason"],
            "coverage": run["coverage"],
            "final_extraction": run["final_extraction"],
            "validation_summary": _validation_summary(validation_results),
            "time_series_summary": series_outcome["summary"],
            "validation_results": validation_results,
            "warnings": _validation_warnings(validation_results),
            "errors": errors,
            "trace": trace,
            "trace_truncated": any(
                event.get("result_truncated", False) for event in trace
            ),
        }


__all__ = [
    "AzureConfigurationError",
    "AzureResponsesError",
    "InvalidWorkbookError",
    "WorkbookValidationError",
    "run_workbook_validation",
]
