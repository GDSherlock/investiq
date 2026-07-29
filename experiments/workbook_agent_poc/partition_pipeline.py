"""Sequential, atomic orchestration for bounded workbook partitions."""

from __future__ import annotations

from collections import deque
import logging
import time
from typing import Any, Callable

from partition_contract import build_partition_envelope
from partition_coverage import PartitionBindingError, PartitionCoverageTracker
from partition_driver import (
    PartitionAuthenticationError,
    PartitionContextLimitError,
    PartitionDriver,
    PartitionDriverError,
    PartitionRefusalError,
    PartitionStructuredOutputError,
    PartitionTransientError,
)
from partition_planner import (
    PartitionLimits,
    PartitionPlanner,
    PartitionPlanningError,
)
from partition_reconciler import PartitionReconciler, ReconciliationError
from workbook_index import WorkbookIndexBuilder
from workbook_tools import WorkbookToolset


logger = logging.getLogger(__name__)


class PartitionPipelineError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        completed_partition_count: int,
        azure_failure: bool = False,
    ) -> None:
        self.code = code
        self.completed_partition_count = completed_partition_count
        self.azure_failure = azure_failure
        self.final_extraction = None
        super().__init__(code)


def run_partitioned_extraction(
    driver: PartitionDriver,
    tools: WorkbookToolset,
    *,
    limits: PartitionLimits | None = None,
) -> dict[str, Any]:
    limits = limits or PartitionLimits()
    partials: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    started = time.monotonic()

    try:
        index = WorkbookIndexBuilder().build(tools)
        planner = PartitionPlanner(limits)
        initial = planner.plan(index)
        queue = deque(initial)
        coverage = PartitionCoverageTracker(index, initial)
    except (PartitionPlanningError, PartitionBindingError) as exc:
        raise PartitionPipelineError(
            code=getattr(exc, "code", "partition_planning_failed"),
            completed_partition_count=0,
        ) from exc

    logger.info(
        "partition_planned workbook_hash_prefix=%s planner_version=%s partition_count=%s",
        index.workbook_version[:12],
        "partition-v1",
        len(initial),
    )
    context_split_counts = {
        partition.partition_id: 0 for partition in initial
    }
    raw_evidence_bytes = 0

    def fail(
        code: str,
        *,
        azure_failure: bool = False,
        cause: Exception | None = None,
    ) -> None:
        completed = len(partials)
        partials.clear()
        logger.error(
            "partition_failed workbook_hash_prefix=%s terminal_code=%s completed_partitions=%s",
            index.workbook_version[:12],
            code,
            completed,
        )
        error = PartitionPipelineError(
            code=code,
            completed_partition_count=completed,
            azure_failure=azure_failure,
        )
        if cause is None:
            raise error
        raise error from cause

    while queue:
        if time.monotonic() - started > limits.deadline_seconds:
            fail("partition_deadline_exceeded")
        max_calls = int(getattr(driver, "max_calls_per_operation", 1))
        if int(getattr(driver, "call_count", 0)) + max_calls > limits.max_azure_calls:
            fail("partition_call_limit_exceeded")

        partition = queue.popleft()
        if (
            raw_evidence_bytes + partition.raw_evidence_bytes
            > limits.max_raw_evidence_bytes_per_run
        ):
            fail("partition_raw_evidence_limit_exceeded")
        raw_evidence_bytes += partition.raw_evidence_bytes
        envelope = build_partition_envelope(index, partition)

        logger.info(
            "partition_call_started workbook_hash_prefix=%s partition_id=%s sheet_name=%s primary_range=%s estimated_total_tokens=%s estimated_raw_tokens=%s request_bytes=%s",
            index.workbook_version[:12],
            partition.partition_id,
            partition.sheet_name,
            partition.primary_range,
            partition.estimated_total_tokens,
            partition.estimated_raw_tokens,
            partition.request_bytes,
        )
        try:
            partial = driver.extract(partition, envelope)
        except PartitionContextLimitError as exc:
            context_splits = context_split_counts.get(partition.partition_id, 0)
            if context_splits >= limits.max_context_splits_per_partition:
                fail(
                    "partition_context_limit_exhausted",
                    azure_failure=True,
                    cause=exc,
                )
            try:
                children = planner.split(index, partition)
                coverage.replace_for_split(partition, children)
            except (PartitionPlanningError, PartitionBindingError) as split_exc:
                fail(
                    "partition_context_split_failed",
                    azure_failure=True,
                    cause=split_exc,
                )
            for child in children:
                context_split_counts[child.partition_id] = context_splits + 1
            queue.extendleft(reversed(children))
            trace.append({
                "event": "partition_split",
                "partition_id": partition.partition_id,
                "sheet_name": partition.sheet_name,
                "primary_range": partition.primary_range,
                "child_partition_ids": [
                    child.partition_id for child in children
                ],
            })
            logger.warning(
                "partition_split workbook_hash_prefix=%s partition_id=%s sheet_name=%s primary_range=%s split_count=%s",
                index.workbook_version[:12],
                partition.partition_id,
                partition.sheet_name,
                partition.primary_range,
                coverage.summary()["split_count"],
            )
            continue
        except PartitionAuthenticationError as exc:
            fail(exc.code, azure_failure=True, cause=exc)
        except PartitionTransientError as exc:
            fail(exc.code, azure_failure=True, cause=exc)
        except PartitionStructuredOutputError as exc:
            fail(exc.code, cause=exc)
        except PartitionDriverError as exc:
            fail(exc.code, azure_failure=True, cause=exc)

        try:
            coverage.record_completed(partition, partial)
        except PartitionBindingError as exc:
            fail("partition_binding_failed", cause=exc)
        partials.append(partial)
        request_ids = getattr(driver, "request_ids", [])
        request_id = request_ids[-1] if request_ids else None
        trace.append({
            "event": "partition_completed",
            "partition_id": partition.partition_id,
            "sheet_name": partition.sheet_name,
            "primary_range": partition.primary_range,
            "estimated_total_tokens": partition.estimated_total_tokens,
            "estimated_raw_tokens": partition.estimated_raw_tokens,
            "request_bytes": partition.request_bytes,
            "azure_request_id": request_id,
        })
        logger.info(
            "partition_completed workbook_hash_prefix=%s partition_id=%s sheet_name=%s primary_range=%s azure_request_id=%s",
            index.workbook_version[:12],
            partition.partition_id,
            partition.sheet_name,
            partition.primary_range,
            request_id,
        )

    if not coverage.submission_allowed():
        fail("partition_coverage_incomplete")

    def bounded_conflict_resolver(
        conflict_envelope: dict[str, Any],
    ) -> dict[str, Any] | None:
        resolver: Callable[[dict[str, Any]], dict[str, Any] | None] | None = getattr(
            driver,
            "resolve_conflict",
            None,
        )
        if resolver is None:
            return None
        if time.monotonic() - started > limits.deadline_seconds:
            fail("partition_deadline_exceeded")
        max_calls = int(getattr(driver, "max_calls_per_operation", 1))
        if int(getattr(driver, "call_count", 0)) + max_calls > limits.max_azure_calls:
            fail("partition_call_limit_exceeded")
        try:
            return resolver(conflict_envelope)
        except PartitionAuthenticationError as exc:
            fail(exc.code, azure_failure=True, cause=exc)
        except PartitionTransientError as exc:
            fail(exc.code, azure_failure=True, cause=exc)
        except PartitionRefusalError as exc:
            fail(exc.code, azure_failure=True, cause=exc)
        except PartitionDriverError as exc:
            fail(exc.code, cause=exc)
        return None

    try:
        outcome = PartitionReconciler(
            max_reconciliation_calls=limits.max_reconciliation_calls
        ).reconcile(
            index,
            partials,
            conflict_resolver=bounded_conflict_resolver,
        )
    except ReconciliationError as exc:
        fail(exc.code, cause=exc)

    coverage_summary = coverage.summary()
    coverage_summary.update({
        "total_sheets": len(index.manifest["sheets"]),
        "content_sheets": len(index.content_sheets),
        "fully_observed_sheets": len(index.content_sheets),
        "workbook_non_empty_cells": index.non_empty_cell_count,
        "raw_evidence_bytes": raw_evidence_bytes,
        "azure_call_count": int(getattr(driver, "call_count", 0)),
        "reconciliation_calls": outcome.reconciliation_calls,
    })
    return {
        "final_extraction": outcome.final_extraction,
        "submitted": True,
        "stop_reason": "submitted",
        "coverage": coverage_summary,
        "trace": trace,
        "iterations": len(trace),
    }


__all__ = ["PartitionPipelineError", "run_partitioned_extraction"]
