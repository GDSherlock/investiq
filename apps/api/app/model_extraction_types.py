"""Shared value types and sanitized errors for Model Extraction persistence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
import uuid


class ModelExtractionPersistenceError(RuntimeError):
    """Base error for persistence operations safe to translate at an API boundary."""


class WorkbookIntegrityError(ModelExtractionPersistenceError):
    """Stored workbook bytes do not match their immutable catalog metadata."""


class WorkbookVersionNotFound(ModelExtractionPersistenceError):
    """The requested workbook version or storage location does not exist."""


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
