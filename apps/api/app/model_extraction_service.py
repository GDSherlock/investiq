"""Synchronous T1/T2/T3 orchestration for durable Model Extraction output."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any, Callable
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.orm import Session

from .model_extraction_models import ModelVersion, WorkbookVersion
from .model_extraction_repository import (
    ModelExtractionRepository,
    WorkbookVersionRepository,
)
from .model_extraction_types import (
    CanonicalSourceConflictError,
    FinancialEntityIdFactory,
    ModelExtractionPersistenceError,
    ModelVersionNotFound,
    PersistenceRetryNotAllowed,
    WorkbookTooLargeError,
    WorkbookVersionNotFound,
    json_safe,
)
from .workbook_storage import (
    DatabaseWorkbookStorage,
    WorkbookStorage,
    WorkbookStorageLocation,
)
from .workbook_validation import (
    InvalidWorkbookError,
    WorkbookToolset,
    role_family,
    run_workbook_validation,
)


_PARAMETER_BUCKET_ORDER = (
    "parameter_candidates",
    "derived_value_candidates",
    "unclassified_inputs",
    "review_candidates",
    "all_assumption_candidates",
    "output_candidates",
)
_CANONICAL_PARAMETER_ROLES = {
    "assumption",
    "hardcoded_input",
    "scenario_input",
    "parameter",
    "derived",
    "formula_derived_value",
    "scenario_selector",
}
_SOURCE_VALID_STATUSES = {"validated", "validated_null"}
_DEFAULT_MAX_WORKBOOK_BYTES = 25 * 1024 * 1024


class ModelExtractionPersistenceService:
    """Persist the current synchronous extraction without changing its execution model."""

    def __init__(
        self,
        session: Session,
        validation_runner: Callable[[bytes, str], dict[str, Any]] = run_workbook_validation,
        *,
        storage: WorkbookStorage | None = None,
        repository: ModelExtractionRepository | None = None,
        workbook_repository: WorkbookVersionRepository | None = None,
        max_workbook_bytes: int | None = None,
    ):
        self._session = session
        self._validation_runner = validation_runner
        self._storage = storage or DatabaseWorkbookStorage(session)
        self._repository = repository or ModelExtractionRepository(session)
        self._workbook_repository = workbook_repository or WorkbookVersionRepository(
            session,
            self._storage,
        )
        configured_limit = (
            max_workbook_bytes
            if max_workbook_bytes is not None
            else os.getenv(
                "MODEL_EXTRACTION_MAX_WORKBOOK_BYTES",
                str(_DEFAULT_MAX_WORKBOOK_BYTES),
            )
        )
        try:
            self._max_workbook_bytes = int(configured_limit)
        except (TypeError, ValueError) as exc:
            raise ModelExtractionPersistenceError(
                "Model Extraction workbook size limit is invalid"
            ) from exc
        if self._max_workbook_bytes <= 0:
            raise ModelExtractionPersistenceError(
                "Model Extraction workbook size limit must be positive"
            )

    def process_upload(self, file_bytes: bytes, filename: str) -> dict[str, Any]:
        payload = bytes(file_bytes)
        if len(payload) > self._max_workbook_bytes:
            raise WorkbookTooLargeError(len(payload), self._max_workbook_bytes)
        self._validate_workbook(payload)

        try:
            workbook_version = self._workbook_repository.get_or_create(payload, filename)
            model_version = self._repository.create_model_version(
                workbook_version.id,
                filename,
            )
            self._session.commit()
        except ModelExtractionPersistenceError:
            self._session.rollback()
            raise
        except Exception as exc:
            self._session.rollback()
            raise ModelExtractionPersistenceError(
                "Model Extraction identity persistence failed"
            ) from exc

        try:
            result = self._validation_runner(payload, filename)
            if not isinstance(result, dict):
                raise TypeError("Model Extraction runner must return an object")
        except Exception:
            self._record_runner_failure(model_version.id)
            raise

        filtered_result = _strip_dependency_evidence(json_safe(deepcopy(result)))
        if not result.get("submitted"):
            self._repository.record_extraction_failure(
                model_version.id,
                submitted=False,
                stop_reason=_optional_text(result.get("stop_reason")),
                error_code=_first_error_code(result) or "AGENT_INCOMPLETE",
                error_message="Model Extraction stopped before a canonical submission",
                driver_meta=_optional_dict(filtered_result.get("driver_meta")),
                coverage=_optional_dict(filtered_result.get("coverage")),
                validation_summary=_optional_dict(
                    filtered_result.get("validation_summary")
                ),
                time_series_summary=_optional_dict(
                    filtered_result.get("time_series_summary")
                ),
                validation_results=filtered_result.get("validation_results"),
            )
            self._session.commit()
            response = deepcopy(result)
            response["workbook_version_id"] = None
            response["model_version_id"] = None
            return response

        validation_status = _aggregate_validation_status(filtered_result)
        self._save_snapshot_with_retry(
            model_version.id,
            filtered_result,
            _optional_text(result.get("stop_reason")),
            validation_status,
        )

        self._persist_canonical_snapshot(
            model_version.id,
            workbook_version.id,
            filtered_result,
            validation_status,
        )

        response = deepcopy(result)
        response["workbook_version_id"] = workbook_version.id
        response["model_version_id"] = model_version.id
        return response

    def retry_canonical_persistence(self, model_version_id: str) -> tuple[str, str]:
        model_version = self._session.get(ModelVersion, model_version_id)
        if model_version is None:
            self._session.rollback()
            raise ModelVersionNotFound("Model version was not found")
        workbook_version_id = model_version.workbook_version_id
        if model_version.status == "materialized":
            self._session.commit()
            return model_version.id, workbook_version_id
        if model_version.status not in {"extracted", "persistence_failed"}:
            status = model_version.status
            self._session.rollback()
            raise PersistenceRetryNotAllowed(
                f"Persistence retry is not allowed from status {status}"
            )

        snapshot = self._repository._load_snapshot_for_retry(model_version_id)
        validation_status = _aggregate_validation_status(snapshot)
        self._persist_canonical_snapshot(
            model_version_id,
            workbook_version_id,
            snapshot,
            validation_status,
        )
        return model_version_id, workbook_version_id

    def _validate_workbook(self, file_bytes: bytes) -> None:
        try:
            WorkbookToolset(file_bytes=file_bytes)
        except (BadZipFile, InvalidFileException, EOFError, ValueError, OSError) as exc:
            raise InvalidWorkbookError(
                "The upload is not a readable OOXML workbook."
            ) from exc

    def _record_runner_failure(self, model_version_id: str) -> None:
        try:
            self._session.rollback()
            self._repository.record_extraction_failure(
                model_version_id,
                submitted=False,
                stop_reason="runner_exception",
                error_code="EXTRACTION_ERROR",
                error_message="Model Extraction pipeline failed",
            )
            self._session.commit()
        except Exception:
            self._session.rollback()

    def _save_snapshot_with_retry(
        self,
        model_version_id: str,
        filtered_result: dict[str, Any],
        stop_reason: str | None,
        validation_status: str,
    ) -> None:
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                self._repository.save_extraction_snapshot(
                    model_version_id,
                    filtered_result,
                    submitted=True,
                    stop_reason=stop_reason,
                    validation_status=validation_status,
                    driver_meta=_optional_dict(filtered_result.get("driver_meta")),
                    coverage=_optional_dict(filtered_result.get("coverage")),
                    validation_summary=_optional_dict(
                        filtered_result.get("validation_summary")
                    ),
                    time_series_summary=_optional_dict(
                        filtered_result.get("time_series_summary")
                    ),
                    validation_results=filtered_result.get("validation_results"),
                )
                self._session.commit()
                return
            except Exception as exc:
                last_error = exc
                self._session.rollback()

        try:
            self._repository.record_extraction_failure(
                model_version_id,
                submitted=True,
                stop_reason=stop_reason,
                error_code="SNAPSHOT_PERSISTENCE_FAILED",
                error_message="Model Extraction snapshot persistence failed",
                driver_meta=_optional_dict(filtered_result.get("driver_meta")),
                coverage=_optional_dict(filtered_result.get("coverage")),
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
        raise ModelExtractionPersistenceError(
            "Model Extraction snapshot persistence failed"
        ) from last_error

    def _persist_canonical_snapshot(
        self,
        model_version_id: str,
        workbook_version_id: str,
        snapshot: dict[str, Any],
        validation_status: str,
    ) -> None:
        try:
            workbook_version = self._session.get(WorkbookVersion, workbook_version_id)
            if workbook_version is None:
                raise WorkbookVersionNotFound("Workbook version was not found")
            location = WorkbookStorageLocation(
                workbook_version.storage_type,
                workbook_version.storage_ref,
            )
            workbook_bytes = self._storage.load(location)
            tools = WorkbookToolset(file_bytes=workbook_bytes)
            parameters = _canonicalize_parameters(model_version_id, snapshot, tools)
            financial_series, values = _canonicalize_financial_series(
                model_version_id,
                snapshot,
                tools,
            )
            self._repository.persist_canonical_model(
                model_version_id,
                parameters=parameters,
                financial_series=financial_series,
                financial_series_values=values,
                validation_status=validation_status,
            )
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            try:
                self._repository.mark_status(
                    model_version_id,
                    "persistence_failed",
                    error_code="CANONICAL_PERSISTENCE_FAILED",
                    error_message="Canonical Model Extraction persistence failed",
                    validation_status=validation_status,
                )
                self._session.commit()
            except Exception:
                self._session.rollback()
            if isinstance(exc, ModelExtractionPersistenceError):
                raise
            raise ModelExtractionPersistenceError(
                "Canonical Model Extraction persistence failed"
            ) from exc


def _canonicalize_parameters(
    model_version_id: str,
    snapshot: dict[str, Any],
    tools: WorkbookToolset,
) -> list[dict[str, Any]]:
    final_extraction = _required_dict(snapshot.get("final_extraction"), "final_extraction")
    validation_results = snapshot.get("validation_results") or []
    if not isinstance(validation_results, list):
        raise ModelExtractionPersistenceError("Validation results must be a list")
    validation_by_key = {
        (result.get("_bucket"), result.get("candidate_id")): result
        for result in validation_results
        if isinstance(result, dict) and result.get("candidate_id") is not None
    }

    grouped: dict[
        tuple[str, str],
        list[tuple[int, str, dict[str, Any], dict[str, Any]]],
    ] = {}
    for rank, bucket in enumerate(_PARAMETER_BUCKET_ORDER):
        candidates = final_extraction.get(bucket) or []
        if not isinstance(candidates, list):
            raise ModelExtractionPersistenceError(f"{bucket} must be a list")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            validation = validation_by_key.get((bucket, candidate.get("candidate_id")))
            if validation is None or not _is_canonical_parameter_validation(validation):
                continue
            source = _candidate_source(candidate)
            if source is None:
                continue
            sheet_name, cell = source
            grouped.setdefault((sheet_name, cell), []).append(
                (rank, bucket, candidate, validation)
            )

    id_factory = FinancialEntityIdFactory(model_version_id)
    rows: list[dict[str, Any]] = []
    for (sheet_name, submitted_cell), candidates in sorted(grouped.items()):
        role_families = {
            role_family(_optional_text(item[3].get("validated_role")))
            for item in candidates
        }
        values = {
            json.dumps(json_safe(item[3].get("validated_value")), sort_keys=True)
            for item in candidates
        }
        if len(role_families) > 1 or len(values) > 1:
            raise CanonicalSourceConflictError(
                f"Canonical candidates disagree at {sheet_name}!{submitted_cell}"
            )

        _rank, bucket, candidate, validation = min(
            candidates,
            key=lambda item: (item[0], str(item[2].get("candidate_id") or "")),
        )
        fact = tools.get_cell(sheet_name, submitted_cell)
        source_cell = str(fact["cell"]).upper()
        candidate_id = candidate.get("candidate_id")
        rows.append(
            {
                "id": id_factory.parameter_id(sheet_name, source_cell),
                "model_version_id": model_version_id,
                "entity_kind": "parameter",
                "llm_candidate_alias": str(candidate_id) if candidate_id is not None else None,
                "source_bucket": bucket,
                "label": str(
                    candidate.get("original_label")
                    or validation.get("original_label")
                    or candidate_id
                    or fact["source_reference"]
                ),
                "category": candidate.get("category"),
                "canonical_name": candidate.get("canonical_name"),
                "submitted_role": str(
                    candidate.get("submitted_role")
                    or validation.get("submitted_role")
                    or "unknown"
                ),
                "validated_role": str(validation.get("validated_role") or "unknown"),
                "raw_value_json": json_safe(
                    candidate.get("raw_value", candidate.get("value"))
                ),
                "validated_value_json": json_safe(fact.get("raw_value")),
                "unit": candidate.get("unit"),
                "scenario": candidate.get("scenario"),
                "period_json": json_safe(candidate.get("period")),
                "source_sheet": sheet_name,
                "source_cell": source_cell,
                "exact_formula": fact.get("formula"),
                "formula_status": str(fact.get("formula_status") or "unknown"),
                "source_validation_status": str(
                    validation.get("source_validation_status") or "unknown"
                ),
                "role_validation_status": str(
                    validation.get("role_validation_status") or "unknown"
                ),
                "validation_status": str(
                    validation.get("validation_status") or "unknown"
                ),
                "data_type": fact.get("data_type"),
                "number_format": fact.get("number_format"),
                "llm_confidence": candidate.get("llm_confidence"),
                "validation_confidence": validation.get("validation_confidence"),
                "reasoning_summary": candidate.get("reasoning_summary"),
                "validation_warnings_json": json_safe(
                    validation.get("validation_warnings") or []
                ),
            }
        )
    return rows


def _canonicalize_financial_series(
    model_version_id: str,
    snapshot: dict[str, Any],
    tools: WorkbookToolset,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    final_extraction = _required_dict(snapshot.get("final_extraction"), "final_extraction")
    submitted_series = final_extraction.get("financial_series") or []
    if not isinstance(submitted_series, list):
        raise ModelExtractionPersistenceError("financial_series must be a list")

    id_factory = FinancialEntityIdFactory(model_version_id)
    series_rows: list[dict[str, Any]] = []
    value_rows: list[dict[str, Any]] = []
    for submitted in submitted_series:
        if not isinstance(submitted, dict):
            raise ModelExtractionPersistenceError("Canonical financial series must be objects")
        period_axis = _required_dict(submitted.get("period_axis"), "period_axis")
        value_axis = _required_dict(submitted.get("value_axis"), "value_axis")
        periods = period_axis.get("periods")
        values = value_axis.get("values")
        if not isinstance(periods, list) or not isinstance(values, list):
            raise ModelExtractionPersistenceError("Canonical series axes must be lists")
        if len(periods) != len(values):
            raise ModelExtractionPersistenceError(
                "Canonical series period and value axes are not aligned"
            )

        period_source_range = str(period_axis.get("source_range") or "")
        value_source_range = str(value_axis.get("source_range") or "")
        if not period_source_range or not value_source_range:
            raise ModelExtractionPersistenceError("Canonical series source ranges are required")
        series_id = id_factory.series_id(
            period_source_range,
            value_source_range,
            _optional_text(submitted.get("scenario")),
            _optional_text(submitted.get("entity")),
            _optional_text(submitted.get("unit")),
            _optional_text(submitted.get("currency")),
        )
        label_sheet = None
        label_cell = None
        if submitted.get("label_reference"):
            label_sheet, label_cell = _split_qualified_cell(
                str(submitted["label_reference"])
            )
        series_rows.append(
            {
                "id": series_id,
                "model_version_id": model_version_id,
                "entity_kind": "financial_series",
                "llm_series_alias": _optional_text(submitted.get("series_id")),
                "label": str(submitted.get("label") or submitted.get("series_id") or series_id),
                "category": submitted.get("category"),
                "semantic_role": "financial_series",
                "unit": submitted.get("unit"),
                "frequency": submitted.get("frequency"),
                "orientation": str(submitted.get("orientation") or "unknown"),
                "scenario": submitted.get("scenario"),
                "entity": submitted.get("entity"),
                "currency": submitted.get("currency"),
                "calculation_type": str(submitted.get("calculation_type") or "unknown"),
                "period_source_range": period_source_range,
                "value_source_range": value_source_range,
                "label_source_sheet": label_sheet,
                "label_source_cell": label_cell,
                "materialization_status": str(
                    submitted.get("materialization_status") or "materialized"
                ),
                "validation_status": str(
                    submitted.get("validation_status") or "validated"
                ),
                "aliases_json": json_safe(submitted.get("aliases") or []),
                "formula_pattern_json": json_safe(submitted.get("formula_pattern")),
                "warnings_json": json_safe(submitted.get("warnings") or []),
                "reasoning_summary": submitted.get("reasoning_summary"),
                "llm_confidence": submitted.get("llm_confidence"),
            }
        )

        for period_index, (period, value) in enumerate(zip(periods, values)):
            if not isinstance(period, dict) or not isinstance(value, dict):
                raise ModelExtractionPersistenceError(
                    "Canonical financial series points must be objects"
                )
            period_sheet, period_cell = _split_qualified_cell(str(period.get("source_cell")))
            value_sheet, value_cell = _split_qualified_cell(str(value.get("source_cell")))
            period_fact = tools.get_cell(period_sheet, period_cell)
            value_fact = tools.get_cell(value_sheet, value_cell)
            has_formula = value_fact.get("formula") is not None
            value_rows.append(
                {
                    "id": id_factory.value_id(series_id, period_index),
                    "financial_series_id": series_id,
                    "period_index": period_index,
                    "raw_period_label_json": json_safe(period_fact.get("raw_value")),
                    "display_period_label": _optional_text(period.get("display_label")),
                    "period_type": _optional_text(period.get("period_type")),
                    "year": period.get("year"),
                    "quarter": period.get("quarter"),
                    "month": period.get("month"),
                    "is_forecast": period.get("is_forecast"),
                    "value_json": json_safe(value_fact.get("raw_value")),
                    "period_source_sheet": period_sheet,
                    "period_source_cell": str(period_fact["cell"]).upper(),
                    "value_source_sheet": value_sheet,
                    "value_source_cell": str(value_fact["cell"]).upper(),
                    "exact_formula": value_fact.get("formula"),
                    "formula_status": str(value_fact.get("formula_status") or "unknown"),
                    "cached_value_available": bool(
                        has_formula and value_fact.get("raw_value") is not None
                    ),
                    "cached_value_freshness": "unknown" if has_formula else None,
                    "number_format": value_fact.get("number_format"),
                    "data_type": value_fact.get("data_type"),
                }
            )
    return series_rows, value_rows


def _candidate_source(candidate: dict[str, Any]) -> tuple[str, str] | None:
    references = candidate.get("source_references") or []
    if not isinstance(references, list) or not references:
        return None
    reference = references[0]
    if not isinstance(reference, dict):
        return None
    sheet_name = reference.get("sheet_name")
    cell = reference.get("cell")
    if not isinstance(sheet_name, str) or not isinstance(cell, str):
        return None
    return sheet_name, cell.replace("$", "").upper()


def _is_canonical_parameter_validation(validation: dict[str, Any]) -> bool:
    return (
        validation.get("source_validation_status") in _SOURCE_VALID_STATUSES
        and validation.get("validation_status") != "rejected"
        and validation.get("validated_role") in _CANONICAL_PARAMETER_ROLES
    )


def _split_qualified_cell(reference: str) -> tuple[str, str]:
    if "!" not in reference:
        raise ModelExtractionPersistenceError(
            "Canonical source cell must include its worksheet"
        )
    sheet_name, cell = reference.rsplit("!", 1)
    sheet_name = sheet_name.strip()
    if sheet_name.startswith("'") and sheet_name.endswith("'"):
        sheet_name = sheet_name[1:-1].replace("''", "'")
    cell = cell.replace("$", "").upper()
    if not sheet_name or not cell or ":" in cell:
        raise ModelExtractionPersistenceError("Canonical source cell is invalid")
    return sheet_name, cell


def _aggregate_validation_status(snapshot: dict[str, Any]) -> str:
    validation_results = snapshot.get("validation_results") or []
    if not isinstance(validation_results, list):
        return "review_required"
    statuses = {
        result.get("validation_status")
        for result in validation_results
        if isinstance(result, dict)
    }
    if statuses & {"rejected", "reclassified", "review_required", "validated_null"}:
        return "review_required"
    if "validated_with_warning" in statuses or snapshot.get("warnings"):
        return "validated_with_warning"
    return "validated"


def _strip_dependency_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_dependency_evidence(item)
            for key, item in value.items()
            if key != "dependency_evidence"
        }
    if isinstance(value, list):
        return [_strip_dependency_evidence(item) for item in value]
    return value


def _required_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelExtractionPersistenceError(f"{field_name} must be an object")
    return value


def _optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _first_error_code(result: dict[str, Any]) -> str | None:
    errors = result.get("errors") or []
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], dict):
        return None
    code = errors[0].get("code")
    return str(code) if code is not None else None
