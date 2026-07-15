"""Repositories for durable Model Extraction state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .model_extraction_models import (
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
    ModelVersion,
    WorkbookVersion,
)
from .model_extraction_types import (
    CanonicalPersistenceStateError,
    ModelVersionNotFound,
    WorkbookIntegrityError,
    json_safe,
    new_uuid,
)
from .workbook_storage import WorkbookStorage, WorkbookStorageLocation


class WorkbookVersionRepository:
    """Own workbook identity and catalog metadata without owning byte storage."""

    def __init__(self, session: Session, storage: WorkbookStorage):
        self._session = session
        self._storage = storage

    def get_or_create(
        self,
        content_bytes: bytes,
        original_filename: str,
    ) -> WorkbookVersion:
        payload = bytes(content_bytes)
        if not payload:
            raise WorkbookIntegrityError("Workbook content must not be empty")

        digest = sha256(payload).hexdigest()
        existing = self._session.scalar(
            select(WorkbookVersion).where(WorkbookVersion.sha256 == digest)
        )
        if existing is not None:
            self._verify_existing(existing)
            return existing

        storage_key = f"workbooks/sha256/{digest}.xlsx"
        location = self._storage.location_for(storage_key)
        workbook_version = WorkbookVersion(
            id=new_uuid(),
            sha256=digest,
            original_filename=original_filename,
            storage_type=location.storage_type,
            storage_ref=location.storage_ref,
            file_size=len(payload),
        )

        try:
            with self._session.begin_nested():
                self._session.add(workbook_version)
                self._storage.store_if_absent(location, payload, digest)
                self._session.flush()
        except IntegrityError as exc:
            if not self._is_sha_uniqueness_violation(exc):
                raise
            winner = self._session.scalar(
                select(WorkbookVersion).where(WorkbookVersion.sha256 == digest)
            )
            if winner is None:
                raise
            self._verify_existing(winner)
            return winner

        return workbook_version

    def _verify_existing(self, workbook_version: WorkbookVersion) -> None:
        location = WorkbookStorageLocation(
            workbook_version.storage_type,
            workbook_version.storage_ref,
        )
        self._storage.verify(
            location,
            workbook_version.sha256,
            workbook_version.file_size,
        )

    @staticmethod
    def _is_sha_uniqueness_violation(exc: IntegrityError) -> bool:
        message = str(exc.orig).lower()
        return (
            "uq_workbook_versions_sha256" in message
            or "workbook_versions.sha256" in message
        )


class ModelExtractionRepository:
    """Write model lifecycle and canonical rows inside caller-owned transactions."""

    def __init__(self, session: Session):
        self._session = session

    def create_model_version(
        self,
        workbook_version_id: str,
        upload_filename: str,
    ) -> ModelVersion:
        model_version = ModelVersion(
            id=new_uuid(),
            workbook_version_id=workbook_version_id,
            upload_filename=upload_filename,
            status="extracting",
            validation_status="not_run",
            submitted=False,
        )
        self._session.add(model_version)
        self._session.flush()
        return model_version

    def save_extraction_snapshot(
        self,
        model_version_id: str,
        extraction_snapshot: dict[str, Any],
        *,
        submitted: bool,
        stop_reason: str | None,
        validation_status: str,
        driver_meta: dict[str, Any] | None = None,
        coverage: dict[str, Any] | None = None,
        validation_summary: dict[str, Any] | None = None,
        time_series_summary: dict[str, Any] | None = None,
        validation_results: dict[str, Any] | list[Any] | None = None,
    ) -> ModelVersion:
        model_version = self._get_model_version(model_version_id)
        if model_version.status != "extracting":
            raise CanonicalPersistenceStateError(
                f"Cannot save extraction snapshot from status {model_version.status}"
            )

        model_version.extraction_snapshot_json = json_safe(deepcopy(extraction_snapshot))
        model_version.driver_meta_json = json_safe(driver_meta)
        model_version.coverage_json = json_safe(coverage)
        model_version.validation_summary_json = json_safe(validation_summary)
        model_version.time_series_summary_json = json_safe(time_series_summary)
        model_version.validation_results_json = json_safe(validation_results)
        model_version.submitted = submitted
        model_version.stop_reason = stop_reason
        model_version.validation_status = validation_status
        model_version.status = "extracted"
        model_version.extracted_at = _utcnow()
        self._session.flush()
        return model_version

    def record_extraction_failure(
        self,
        model_version_id: str,
        *,
        submitted: bool,
        stop_reason: str | None,
        error_code: str,
        error_message: str,
        driver_meta: dict[str, Any] | None = None,
        coverage: dict[str, Any] | None = None,
        validation_summary: dict[str, Any] | None = None,
        time_series_summary: dict[str, Any] | None = None,
        validation_results: dict[str, Any] | list[Any] | None = None,
    ) -> ModelVersion:
        model_version = self._get_model_version(model_version_id)
        model_version.submitted = submitted
        model_version.stop_reason = stop_reason
        model_version.driver_meta_json = json_safe(driver_meta)
        model_version.coverage_json = json_safe(coverage)
        model_version.validation_summary_json = json_safe(validation_summary)
        model_version.time_series_summary_json = json_safe(time_series_summary)
        model_version.validation_results_json = json_safe(validation_results)
        model_version.status = "extraction_failed"
        model_version.validation_status = "not_run"
        model_version.error_code = error_code
        model_version.error_message = error_message
        model_version.completed_at = _utcnow()
        self._session.flush()
        return model_version

    def persist_canonical_model(
        self,
        model_version_id: str,
        *,
        parameters: list[dict[str, Any]],
        financial_series: list[dict[str, Any]],
        financial_series_values: list[dict[str, Any]],
        validation_status: str,
    ) -> ModelVersion:
        model_version = self._get_model_version(model_version_id)
        if model_version.status not in {"extracted", "persistence_failed"}:
            raise CanonicalPersistenceStateError(
                f"Cannot persist canonical model from status {model_version.status}"
            )
        if self._canonical_row_count(model_version_id) != 0:
            raise CanonicalPersistenceStateError(
                "Canonical rows already exist for this model version"
            )

        parameter_rows = [ModelParameter(**row) for row in parameters]
        series_rows = [FinancialSeries(**row) for row in financial_series]
        value_rows = [FinancialSeriesValue(**row) for row in financial_series_values]

        self._session.add_all(parameter_rows)
        self._session.flush()
        self._session.add_all(series_rows)
        self._session.flush()
        self._session.add_all(value_rows)
        self._session.flush()

        actual_parameter_count = self._session.scalar(
            select(func.count()).select_from(ModelParameter).where(
                ModelParameter.model_version_id == model_version_id
            )
        )
        actual_series_count = self._session.scalar(
            select(func.count()).select_from(FinancialSeries).where(
                FinancialSeries.model_version_id == model_version_id
            )
        )
        actual_value_count = self._session.scalar(
            select(func.count())
            .select_from(FinancialSeriesValue)
            .join(FinancialSeries)
            .where(FinancialSeries.model_version_id == model_version_id)
        )
        if (
            actual_parameter_count != len(parameter_rows)
            or actual_series_count != len(series_rows)
            or actual_value_count != len(value_rows)
        ):
            raise CanonicalPersistenceStateError(
                "Canonical row counts do not match the persistence request"
            )

        model_version.status = "materialized"
        model_version.validation_status = validation_status
        model_version.completed_at = _utcnow()
        model_version.error_code = None
        model_version.error_message = None
        self._session.flush()
        return model_version

    def mark_status(
        self,
        model_version_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        validation_status: str | None = None,
    ) -> ModelVersion:
        model_version = self._get_model_version(model_version_id)
        model_version.status = status
        model_version.error_code = error_code
        model_version.error_message = error_message
        if validation_status is not None:
            model_version.validation_status = validation_status
        if status in {"materialized", "extraction_failed", "persistence_failed"}:
            model_version.completed_at = _utcnow()
        self._session.flush()
        return model_version

    def _load_snapshot_for_retry(self, model_version_id: str) -> dict[str, Any]:
        model_version = self._get_model_version(model_version_id)
        if model_version.status not in {"extracted", "persistence_failed"}:
            raise CanonicalPersistenceStateError(
                f"Snapshot retry is not allowed from status {model_version.status}"
            )
        if model_version.extraction_snapshot_json is None:
            raise CanonicalPersistenceStateError(
                "Model version has no extraction snapshot for persistence retry"
            )
        return deepcopy(model_version.extraction_snapshot_json)

    def _get_model_version(self, model_version_id: str) -> ModelVersion:
        model_version = self._session.get(ModelVersion, model_version_id)
        if model_version is None:
            raise ModelVersionNotFound("Model version was not found")
        return model_version

    def _canonical_row_count(self, model_version_id: str) -> int:
        parameter_count = self._session.scalar(
            select(func.count()).select_from(ModelParameter).where(
                ModelParameter.model_version_id == model_version_id
            )
        )
        series_count = self._session.scalar(
            select(func.count()).select_from(FinancialSeries).where(
                FinancialSeries.model_version_id == model_version_id
            )
        )
        return int(parameter_count or 0) + int(series_count or 0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
