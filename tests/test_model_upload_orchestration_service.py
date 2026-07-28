from __future__ import annotations

from apps.api.app.calculation_integration_service import CalculationIntegrationError
from apps.api.app.model_upload_orchestration_service import (
    ModelUploadOrchestrationService,
)


class _SuccessfulExtraction:
    def process_upload(self, _file_bytes: bytes, _filename: str) -> dict[str, object]:
        return {
            "submitted": True,
            "model_version_id": "model-version-id",
            "workbook_version_id": "workbook-version-id",
            "warnings": [{"code": "EXTRACTION_WARNING"}],
        }


class _FailingPreparation:
    def prepare(self, _model_version_id: str) -> None:
        raise CalculationIntegrationError(
            "CALCULATION_PREPARATION_FAILED",
            "secret workbook and database details",
            status_code=500,
        )


class _TrackingPreparation:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepare(self, model_version_id: str) -> None:
        self.calls.append(model_version_id)


class _IncompleteExtraction:
    def process_upload(self, _file_bytes: bytes, _filename: str) -> dict[str, object]:
        return {
            "submitted": False,
            "model_version_id": None,
            "workbook_version_id": None,
            "warnings": [],
        }


def test_successful_materialized_upload_prepares_exactly_once() -> None:
    preparation = _TrackingPreparation()
    service = ModelUploadOrchestrationService(
        session=None,  # type: ignore[arg-type]
        validation_runner=lambda _content, _filename: {},
        extraction_service=_SuccessfulExtraction(),  # type: ignore[arg-type]
        calculation_service=preparation,  # type: ignore[arg-type]
    )

    result = service.process_upload(b"workbook", "model.xlsx")

    assert result["submitted"] is True
    assert preparation.calls == ["model-version-id"]


def test_incomplete_extraction_does_not_prepare() -> None:
    preparation = _TrackingPreparation()
    service = ModelUploadOrchestrationService(
        session=None,  # type: ignore[arg-type]
        validation_runner=lambda _content, _filename: {},
        extraction_service=_IncompleteExtraction(),  # type: ignore[arg-type]
        calculation_service=preparation,  # type: ignore[arg-type]
    )

    result = service.process_upload(b"workbook", "model.xlsx")

    assert result["submitted"] is False
    assert preparation.calls == []


def test_preparation_failure_preserves_upload_and_appends_sanitized_warning() -> None:
    service = ModelUploadOrchestrationService(
        session=None,  # type: ignore[arg-type]
        validation_runner=lambda _content, _filename: {},
        extraction_service=_SuccessfulExtraction(),  # type: ignore[arg-type]
        calculation_service=_FailingPreparation(),  # type: ignore[arg-type]
    )

    result = service.process_upload(b"workbook", "model.xlsx")

    assert result["submitted"] is True
    assert result["model_version_id"] == "model-version-id"
    assert result["workbook_version_id"] == "workbook-version-id"
    assert result["warnings"] == [
        {"code": "EXTRACTION_WARNING"},
        {
            "code": "CALCULATION_PREPARATION_FAILED",
            "message": "Calculation preparation failed.",
            "model_version_id": "model-version-id",
            "workbook_version_id": "workbook-version-id",
        },
    ]
    assert "secret" not in str(result)
