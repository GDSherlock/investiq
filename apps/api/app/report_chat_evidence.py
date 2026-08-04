"""Stable evidence catalog for cited persona report generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .report_personas import get_report_persona
from .schemas import UUIDString


_FIXED_GENERATION_PROMPTS = frozenset(
    get_report_persona(persona_id).primary_prompt.casefold()
    for persona_id in ("IM", "CF", "BD", "FA", "PO")
)


class ReportEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    id: StrictStr = Field(pattern=r"^[MU][1-9][0-9]*$")
    source_type: Literal["model", "user"]
    label: StrictStr = Field(min_length=1)
    content: dict[str, Any]
    source_ref: StrictStr = Field(min_length=1)
    message_id: UUIDString | None = None


class ReportEvidenceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    items: list[ReportEvidenceItem]

    def by_id(self) -> dict[str, ReportEvidenceItem]:
        return {item.id: item for item in self.items}


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _prune_unavailable(value: object) -> object | None:
    if isinstance(value, Mapping):
        if value.get("availability_status") == "unavailable":
            return None
        result: dict[str, object] = {}
        for key, item in value.items():
            if item is None:
                continue
            pruned = _prune_unavailable(item)
            if pruned is not None:
                result[str(key)] = pruned
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            pruned
            for item in value
            if (pruned := _prune_unavailable(item)) is not None
        ]
    return value


def _source_ref(item: Mapping[str, Any], fallback: str) -> str:
    raw_ids = _sequence(item.get("source_ids"))
    source_ids = [str(source_id) for source_id in raw_ids if source_id]
    if source_ids:
        return ",".join(source_ids)
    parameter_id = item.get("parameter_id")
    if parameter_id:
        return str(parameter_id)
    source_sheet = item.get("source_sheet")
    source_cell = item.get("source_cell")
    if source_sheet and source_cell:
        return f"{source_sheet}!{source_cell}"
    return fallback


class ReportChatEvidenceBuilder:
    def build(
        self,
        *,
        snapshot: Mapping[str, object],
        messages: Iterable[object],
    ) -> ReportEvidenceCatalog:
        model_items = self._model_items(snapshot)
        items = [
            ReportEvidenceItem(
                id=f"M{index}",
                source_type="model",
                label=label,
                content=content,
                source_ref=source_ref,
            )
            for index, (label, content, source_ref) in enumerate(
                model_items, start=1
            )
        ]
        ordered_messages = sorted(
            (
                message
                for message in messages
                if getattr(message, "role", None) == "user"
            ),
            key=lambda message: (
                (
                    getattr(message, "created_at").isoformat()
                    if isinstance(getattr(message, "created_at", None), datetime)
                    else ""
                ),
                str(getattr(message, "id", "")),
            ),
        )
        user_index = 0
        for message in ordered_messages:
            content_json = getattr(message, "content_json", None)
            content = _mapping(content_json)
            text = content.get("text") if content is not None else None
            if not isinstance(text, str) or not text.strip():
                continue
            if text.strip().casefold() in _FIXED_GENERATION_PROMPTS:
                continue
            user_index += 1
            created_at = getattr(message, "created_at", None)
            timestamp = (
                created_at.isoformat()
                if isinstance(created_at, datetime)
                else "unknown time"
            )
            message_id = str(getattr(message, "id"))
            items.append(
                ReportEvidenceItem(
                    id=f"U{user_index}",
                    source_type="user",
                    label=f"User message at {timestamp}",
                    content={"text": text, "created_at": timestamp},
                    source_ref=f"message:{message_id}",
                    message_id=message_id,
                )
            )
        return ReportEvidenceCatalog(items=items)

    def _model_items(
        self, snapshot: Mapping[str, object]
    ) -> list[tuple[str, dict[str, Any], str]]:
        items: list[tuple[str, dict[str, Any], str]] = []
        calculation = _mapping(snapshot.get("calculation")) or {}
        overview = _mapping(calculation.get("overview")) or {}
        cash_flow = _mapping(calculation.get("cash_flow")) or {}

        for raw_kpi in _sequence(overview.get("kpis")):
            kpi = _mapping(raw_kpi)
            if (
                kpi is None
                or kpi.get("availability_status") == "unavailable"
                or kpi.get("value") is None
            ):
                continue
            pruned = _prune_unavailable(kpi)
            if not isinstance(pruned, dict):
                continue
            label = str(kpi.get("label") or kpi.get("slot") or "Overview KPI")
            items.append(
                (label, pruned, _source_ref(kpi, f"overview:{label}"))
            )

        for area, charts in (
            ("overview", overview.get("charts")),
            ("cash-flow", cash_flow.get("charts")),
        ):
            for raw_chart in _sequence(charts):
                chart = _mapping(raw_chart)
                if chart is None or chart.get("availability_status") == "unavailable":
                    continue
                for raw_series in _sequence(chart.get("series")):
                    series = _mapping(raw_series)
                    if (
                        series is None
                        or series.get("availability_status") == "unavailable"
                    ):
                        continue
                    available_points = []
                    point_source_ids: list[str] = []
                    for raw_point in _sequence(series.get("points")):
                        point = _mapping(raw_point)
                        if (
                            point is None
                            or point.get("availability_status") == "unavailable"
                            or point.get("value") is None
                        ):
                            continue
                        pruned_point = _prune_unavailable(point)
                        if isinstance(pruned_point, dict):
                            available_points.append(pruned_point)
                        point_source_ids.extend(
                            str(source_id)
                            for source_id in _sequence(point.get("source_ids"))
                            if source_id
                        )
                    if not available_points:
                        continue
                    label = str(
                        series.get("label")
                        or series.get("role")
                        or chart.get("title")
                        or "Series"
                    )
                    content = {
                        "chart": chart.get("title"),
                        "role": series.get("role"),
                        "label": label,
                        "unit": series.get("unit"),
                        "points": available_points,
                    }
                    pruned_content = _prune_unavailable(content)
                    if not isinstance(pruned_content, dict):
                        continue
                    series_ids = [
                        str(source_id)
                        for source_id in _sequence(series.get("source_ids"))
                        if source_id
                    ]
                    source_ref = ",".join(
                        dict.fromkeys(series_ids + point_source_ids)
                    ) or f"{area}:{chart.get('slot', 'chart')}:{series.get('role', label)}"
                    items.append((label, pruned_content, source_ref))

        for raw_assumption in _sequence(snapshot.get("assumptions")):
            assumption = _mapping(raw_assumption)
            if assumption is None or assumption.get("value") is None:
                continue
            pruned = _prune_unavailable(assumption)
            if not isinstance(pruned, dict):
                continue
            label = str(
                assumption.get("label")
                or assumption.get("business_role")
                or "Assumption"
            )
            items.append(
                (
                    label,
                    pruned,
                    _source_ref(assumption, f"assumption:{label}"),
                )
            )

        sensitivity = _mapping(snapshot.get("sensitivity"))
        if sensitivity is not None:
            response = _prune_unavailable(sensitivity.get("response"))
            if isinstance(response, dict) and response:
                analysis_id = str(sensitivity.get("analysis_id") or "latest")
                items.append(
                    (
                        "Sensitivity analysis",
                        response,
                        f"sensitivity:{analysis_id}",
                    )
                )

        monte_carlo = _mapping(snapshot.get("monte_carlo"))
        if monte_carlo is not None:
            artifact = _mapping(monte_carlo.get("result_artifact")) or {}
            monte_carlo_id = str(
                monte_carlo.get("monte_carlo_run_id") or "latest"
            )
            for raw_metric in _sequence(artifact.get("metrics")):
                metric = _mapping(raw_metric)
                if (
                    metric is None
                    or metric.get("availability_status") == "unavailable"
                ):
                    continue
                pruned = _prune_unavailable(metric)
                if not isinstance(pruned, dict) or not pruned:
                    continue
                label = str(
                    metric.get("label") or metric.get("role") or "Monte Carlo metric"
                )
                role = str(metric.get("role") or label)
                items.append(
                    (
                        label,
                        pruned,
                        f"monte-carlo:{monte_carlo_id}:{role}",
                    )
                )

        return items
