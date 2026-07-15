"""Shared value types and sanitized errors for Model Extraction persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
import uuid


class ModelExtractionPersistenceError(RuntimeError):
    """Base error for persistence operations safe to translate at an API boundary."""


class WorkbookIntegrityError(ModelExtractionPersistenceError):
    """Stored workbook bytes do not match their immutable catalog metadata."""


class WorkbookVersionNotFound(ModelExtractionPersistenceError):
    """The requested workbook version or storage location does not exist."""


class ModelVersionNotFound(ModelExtractionPersistenceError):
    """The requested model version does not exist."""


class CanonicalPersistenceStateError(ModelExtractionPersistenceError):
    """Canonical rows cannot be written from the model version's current state."""


FinancialEntityKind = Literal["parameter", "financial_series"]


@dataclass(frozen=True)
class FinancialEntityRef:
    id: str
    model_version_id: str
    entity_kind: FinancialEntityKind
    label: str

    def __post_init__(self) -> None:
        if self.entity_kind not in {"parameter", "financial_series"}:
            raise ValueError(f"Unsupported financial entity kind: {self.entity_kind}")


@dataclass(frozen=True)
class FinancialEntityIdFactory:
    """Generate retry-stable IDs with a future shared-entity table namespace."""

    model_version_id: str

    def parameter_id(self, source_sheet: str, source_cell: str) -> str:
        key = "|".join(
            [
                "financial_entity",
                "parameter",
                source_sheet,
                source_cell.upper(),
            ]
        )
        return str(uuid.uuid5(self._model_namespace, key))

    def series_id(
        self,
        period_source_range: str,
        value_source_range: str,
        scenario: str | None,
        entity: str | None,
        unit: str | None,
        currency: str | None,
    ) -> str:
        key = "|".join(
            [
                "financial_entity",
                "financial_series",
                self._component(period_source_range),
                self._component(value_source_range),
                self._component(scenario),
                self._component(entity),
                self._component(unit),
                self._component(currency),
            ]
        )
        return str(uuid.uuid5(self._model_namespace, key))

    @staticmethod
    def value_id(financial_series_id: str, period_index: int) -> str:
        if period_index < 0:
            raise ValueError("period_index must be non-negative")
        key = f"financial_series_value|{period_index}"
        return str(uuid.uuid5(uuid.UUID(financial_series_id), key))

    @property
    def _model_namespace(self) -> uuid.UUID:
        return uuid.UUID(self.model_version_id)

    @staticmethod
    def _component(value: object | None) -> str:
        return "" if value is None else str(value).strip()


def new_uuid() -> str:
    return str(uuid.uuid4())


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
