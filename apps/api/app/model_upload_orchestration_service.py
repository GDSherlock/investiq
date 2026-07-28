"""Compose durable model extraction with deterministic calculation preparation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from .calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from .model_extraction_read_service import ModelExtractionReadService
from .model_extraction_service import ModelExtractionPersistenceService
from .workbook_storage import DatabaseWorkbookStorage


class ModelUploadOrchestrationService:
    """Run calculation preparation after a successful materialized upload."""

    def __init__(
        self,
        session: Session,
        validation_runner: Callable[[bytes, str], dict[str, Any]],
        *,
        extraction_service: ModelExtractionPersistenceService | None = None,
        calculation_service: CalculationIntegrationService | None = None,
    ) -> None:
        self._extraction_service = (
            extraction_service
            or ModelExtractionPersistenceService(
                session=session,
                validation_runner=validation_runner,
            )
        )
        if calculation_service is None:
            read_service = ModelExtractionReadService(
                session,
                DatabaseWorkbookStorage(session),
            )
            calculation_service = CalculationIntegrationService(session, read_service)
        self._calculation_service = calculation_service

    def process_upload(self, file_bytes: bytes, filename: str) -> dict[str, Any]:
        result = self._extraction_service.process_upload(file_bytes, filename)
        model_version_id = result.get("model_version_id")
        workbook_version_id = result.get("workbook_version_id")
        if (
            result.get("submitted") is not True
            or not isinstance(model_version_id, str)
            or not model_version_id
            or not isinstance(workbook_version_id, str)
            or not workbook_version_id
        ):
            return result
        try:
            self._calculation_service.prepare(model_version_id)
        except CalculationIntegrationError:
            warnings = result.get("warnings")
            if not isinstance(warnings, list):
                warnings = []
                result["warnings"] = warnings
            warnings.append(
                {
                    "code": "CALCULATION_PREPARATION_FAILED",
                    "message": "Calculation preparation failed.",
                    "model_version_id": model_version_id,
                    "workbook_version_id": workbook_version_id,
                }
            )
        return result
