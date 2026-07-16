"""Canonical-only reload contract for durable Model Extraction output."""

from __future__ import annotations

from datetime import date, datetime
import math
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model_extraction_models import (
    FinancialSeries,
    FinancialSeriesValue,
    ModelParameter,
    ModelVersion,
    WorkbookVersion,
)
from .model_extraction_types import (
    AmbiguousSourceCellError,
    CanonicalCalculationInput,
    CanonicalFinancialSeries,
    CanonicalFinancialSeriesValue,
    CanonicalParameter,
    FinancialEntity,
    FinancialSeriesNotFound,
    FinancialSeriesValueNotFound,
    FinancialSeriesValueResolution,
    InvalidCellAddress,
    ModelVersionData,
    ModelVersionNotFound,
    ModelVersionNotReady,
    ModelWorkbookMismatch,
    ParameterNotFound,
    ParameterResolution,
    SourceResolvedEntity,
    WorkbookVersionData,
    WorkbookVersionNotFound,
)
from .workbook_storage import WorkbookStorage, WorkbookStorageLocation


_A1_PATTERN = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]{0,6})$")
_MAX_EXCEL_COLUMN = 16_384
_MAX_EXCEL_ROW = 1_048_576


class ModelExtractionReadService:
    """Return typed data sourced exclusively from canonical relational rows."""

    def __init__(self, session: Session, storage: WorkbookStorage):
        self._session = session
        self._storage = storage

    def load_workbook_version(self, workbook_version_id: str) -> WorkbookVersionData:
        workbook_version = self._session.get(WorkbookVersion, workbook_version_id)
        if workbook_version is None:
            raise WorkbookVersionNotFound("Workbook version was not found")
        location = WorkbookStorageLocation(
            workbook_version.storage_type,
            workbook_version.storage_ref,
        )
        content_bytes = self._storage.load(location)
        return WorkbookVersionData(
            id=workbook_version.id,
            sha256=workbook_version.sha256,
            original_filename=workbook_version.original_filename,
            file_size=workbook_version.file_size,
            created_at=workbook_version.created_at,
            content_bytes=content_bytes,
        )

    def load_model_version(
        self,
        model_version_id: str,
        require_materialized: bool = True,
        expected_workbook_version_id: str | None = None,
    ) -> ModelVersionData:
        model_version = self._session.get(ModelVersion, model_version_id)
        if model_version is None:
            raise ModelVersionNotFound("Model version was not found")
        if (
            expected_workbook_version_id is not None
            and model_version.workbook_version_id != expected_workbook_version_id
        ):
            raise ModelWorkbookMismatch("Model version does not use the expected workbook")
        if require_materialized and model_version.status != "materialized":
            raise ModelVersionNotReady(model_version.status)
        return ModelVersionData(
            id=model_version.id,
            workbook_version_id=model_version.workbook_version_id,
            upload_filename=model_version.upload_filename,
            status=model_version.status,
            validation_status=model_version.validation_status,
            submitted=model_version.submitted,
            stop_reason=model_version.stop_reason,
            created_at=model_version.created_at,
            extracted_at=model_version.extracted_at,
            completed_at=model_version.completed_at,
        )

    def list_financial_entities(self, model_version_id: str) -> list[FinancialEntity]:
        entities: list[FinancialEntity] = [
            *self.list_parameters(model_version_id),
            *self.list_financial_series(model_version_id),
        ]
        return sorted(entities, key=lambda item: (item.entity_kind, item.id))

    def list_parameters(self, model_version_id: str) -> list[CanonicalParameter]:
        self.load_model_version(model_version_id)
        rows = self._session.scalars(
            select(ModelParameter)
            .where(ModelParameter.model_version_id == model_version_id)
            .order_by(ModelParameter.id)
        ).all()
        return [self._parameter_data(row) for row in rows]

    def get_parameter(
        self,
        model_version_id: str,
        parameter_id: str,
    ) -> CanonicalParameter:
        self.load_model_version(model_version_id)
        row = self._session.scalar(
            select(ModelParameter).where(
                ModelParameter.id == parameter_id,
                ModelParameter.model_version_id == model_version_id,
            )
        )
        if row is None:
            raise ParameterNotFound(
                "Canonical parameter was not found in the model version"
            )
        return self._parameter_data(row)

    def list_financial_series(
        self,
        model_version_id: str,
    ) -> list[CanonicalFinancialSeries]:
        self.load_model_version(model_version_id)
        rows = self._session.scalars(
            select(FinancialSeries)
            .where(FinancialSeries.model_version_id == model_version_id)
            .order_by(FinancialSeries.id)
        ).all()
        return [self._series_data(row) for row in rows]

    def list_financial_series_values(
        self,
        model_version_id: str,
        financial_series_id: str | None = None,
    ) -> list[CanonicalFinancialSeriesValue]:
        self.load_model_version(model_version_id)
        if financial_series_id is not None:
            owned_series_id = self._session.scalar(
                select(FinancialSeries.id).where(
                    FinancialSeries.id == financial_series_id,
                    FinancialSeries.model_version_id == model_version_id,
                )
            )
            if owned_series_id is None:
                raise FinancialSeriesNotFound(
                    "Financial series was not found in the model version"
                )

        statement = (
            select(FinancialSeriesValue)
            .join(FinancialSeries)
            .where(FinancialSeries.model_version_id == model_version_id)
            .order_by(
                FinancialSeriesValue.financial_series_id,
                FinancialSeriesValue.period_index,
            )
        )
        if financial_series_id is not None:
            statement = statement.where(
                FinancialSeriesValue.financial_series_id == financial_series_id
            )
        rows = self._session.scalars(statement).all()
        return [self._value_data(row) for row in rows]

    def get_financial_series_value(
        self,
        model_version_id: str,
        financial_series_value_id: str,
    ) -> FinancialSeriesValueResolution:
        self.load_model_version(model_version_id)
        row = self._session.execute(
            select(FinancialSeriesValue, FinancialSeries)
            .join(FinancialSeries)
            .where(
                FinancialSeriesValue.id == financial_series_value_id,
                FinancialSeries.model_version_id == model_version_id,
            )
        ).one_or_none()
        if row is None:
            raise FinancialSeriesValueNotFound(
                "Canonical financial-series value was not found in the model version"
            )
        value, series = row
        series_data = self._series_data(series)
        return FinancialSeriesValueResolution(
            entity=series_data.entity_ref,
            series=series_data,
            value=self._value_data(value),
        )

    def get_calculation_input(
        self,
        model_version_id: str,
        target_kind: str,
        target_id: str,
    ) -> CanonicalCalculationInput:
        if target_kind == "parameter":
            parameter = self.get_parameter(model_version_id, target_id)
            return CanonicalCalculationInput(
                target_kind="parameter",
                target_id=parameter.id,
                model_version_id=parameter.model_version_id,
                label=parameter.label,
                category=parameter.category,
                unit=parameter.unit,
                scenario=parameter.scenario,
                period=(
                    str(parameter.period_json)
                    if parameter.period_json is not None
                    else None
                ),
                current_value=parameter.validated_value_json,
                value_type=_canonical_value_type(
                    parameter.validated_value_json,
                    parameter.data_type,
                ),
                source_sheet=parameter.source_sheet,
                source_cell=parameter.source_cell,
                formula_backed=_formula_backed(
                    parameter.exact_formula,
                    parameter.formula_status,
                ),
                source_owner_count=self._source_owner_count(
                    model_version_id,
                    parameter.source_sheet,
                    parameter.source_cell,
                ),
            )
        if target_kind == "financial_series_value":
            resolution = self.get_financial_series_value(model_version_id, target_id)
            series = resolution.series
            value = resolution.value
            return CanonicalCalculationInput(
                target_kind="financial_series_value",
                target_id=value.id,
                model_version_id=series.model_version_id,
                label=series.label,
                category=series.category,
                unit=series.unit,
                scenario=series.scenario,
                period=value.display_period_label,
                current_value=value.value_json,
                value_type=_canonical_value_type(value.value_json, value.data_type),
                source_sheet=value.value_source_sheet,
                source_cell=value.value_source_cell,
                formula_backed=_formula_backed(
                    value.exact_formula,
                    value.formula_status,
                ),
                source_owner_count=self._source_owner_count(
                    model_version_id,
                    value.value_source_sheet,
                    value.value_source_cell,
                ),
            )
        raise ValueError("Calculation input kind is not registered")

    def _source_owner_count(
        self,
        model_version_id: str,
        sheet_name: str,
        cell_address: str,
    ) -> int:
        parameter_count = self._session.scalar(
            select(func.count())
            .select_from(ModelParameter)
            .where(
                ModelParameter.model_version_id == model_version_id,
                ModelParameter.source_sheet == sheet_name,
                ModelParameter.source_cell == cell_address,
            )
        ) or 0
        series_value_count = self._session.scalar(
            select(func.count())
            .select_from(FinancialSeriesValue)
            .join(FinancialSeries)
            .where(
                FinancialSeries.model_version_id == model_version_id,
                FinancialSeriesValue.value_source_sheet == sheet_name,
                FinancialSeriesValue.value_source_cell == cell_address,
            )
        ) or 0
        return parameter_count + series_value_count

    def resolve_entity_by_source_cell(
        self,
        model_version_id: str,
        sheet_name: str,
        cell_address: str,
    ) -> SourceResolvedEntity | None:
        self.load_model_version(model_version_id)
        normalized_cell = _normalize_a1(cell_address)

        parameter = self._session.scalar(
            select(ModelParameter).where(
                ModelParameter.model_version_id == model_version_id,
                ModelParameter.source_sheet == sheet_name,
                ModelParameter.source_cell == normalized_cell,
            )
        )
        series_value_rows = self._session.execute(
            select(FinancialSeriesValue, FinancialSeries)
            .join(FinancialSeries)
            .where(
                FinancialSeries.model_version_id == model_version_id,
                FinancialSeriesValue.value_source_sheet == sheet_name,
                FinancialSeriesValue.value_source_cell == normalized_cell,
            )
        ).all()

        if (parameter is not None and series_value_rows) or len(series_value_rows) > 1:
            raise AmbiguousSourceCellError(
                "Source cell maps to more than one canonical financial entity"
            )
        if parameter is not None:
            parameter_data = self._parameter_data(parameter)
            return ParameterResolution(
                entity=parameter_data.entity_ref,
                parameter=parameter_data,
            )
        if series_value_rows:
            value, series = series_value_rows[0]
            series_data = self._series_data(series)
            return FinancialSeriesValueResolution(
                entity=series_data.entity_ref,
                series=series_data,
                value=self._value_data(value),
            )
        return None

    @staticmethod
    def _parameter_data(row: ModelParameter) -> CanonicalParameter:
        return CanonicalParameter(
            id=row.id,
            model_version_id=row.model_version_id,
            entity_kind="parameter",
            llm_candidate_alias=row.llm_candidate_alias,
            source_bucket=row.source_bucket,
            label=row.label,
            category=row.category,
            canonical_name=row.canonical_name,
            submitted_role=row.submitted_role,
            validated_role=row.validated_role,
            raw_value_json=row.raw_value_json,
            validated_value_json=row.validated_value_json,
            unit=row.unit,
            scenario=row.scenario,
            period_json=row.period_json,
            source_sheet=row.source_sheet,
            source_cell=row.source_cell,
            exact_formula=row.exact_formula,
            formula_status=row.formula_status,
            source_validation_status=row.source_validation_status,
            role_validation_status=row.role_validation_status,
            validation_status=row.validation_status,
            data_type=row.data_type,
            number_format=row.number_format,
            llm_confidence=row.llm_confidence,
            validation_confidence=row.validation_confidence,
            reasoning_summary=row.reasoning_summary,
            validation_warnings_json=row.validation_warnings_json,
            created_at=row.created_at,
        )

    @staticmethod
    def _series_data(row: FinancialSeries) -> CanonicalFinancialSeries:
        return CanonicalFinancialSeries(
            id=row.id,
            model_version_id=row.model_version_id,
            entity_kind="financial_series",
            llm_series_alias=row.llm_series_alias,
            label=row.label,
            category=row.category,
            semantic_role=row.semantic_role,
            unit=row.unit,
            frequency=row.frequency,
            orientation=row.orientation,
            scenario=row.scenario,
            entity=row.entity,
            currency=row.currency,
            calculation_type=row.calculation_type,
            period_source_range=row.period_source_range,
            value_source_range=row.value_source_range,
            label_source_sheet=row.label_source_sheet,
            label_source_cell=row.label_source_cell,
            materialization_status=row.materialization_status,
            validation_status=row.validation_status,
            aliases_json=row.aliases_json,
            formula_pattern_json=row.formula_pattern_json,
            warnings_json=row.warnings_json,
            reasoning_summary=row.reasoning_summary,
            llm_confidence=row.llm_confidence,
            created_at=row.created_at,
        )

    @staticmethod
    def _value_data(row: FinancialSeriesValue) -> CanonicalFinancialSeriesValue:
        return CanonicalFinancialSeriesValue(
            id=row.id,
            financial_series_id=row.financial_series_id,
            period_index=row.period_index,
            raw_period_label_json=row.raw_period_label_json,
            display_period_label=row.display_period_label,
            period_type=row.period_type,
            year=row.year,
            quarter=row.quarter,
            month=row.month,
            is_forecast=row.is_forecast,
            value_json=row.value_json,
            period_source_sheet=row.period_source_sheet,
            period_source_cell=row.period_source_cell,
            value_source_sheet=row.value_source_sheet,
            value_source_cell=row.value_source_cell,
            exact_formula=row.exact_formula,
            formula_status=row.formula_status,
            cached_value_available=row.cached_value_available,
            cached_value_freshness=row.cached_value_freshness,
            number_format=row.number_format,
            data_type=row.data_type,
            created_at=row.created_at,
        )


def _normalize_a1(cell_address: str) -> str:
    match = _A1_PATTERN.fullmatch(cell_address)
    if match is None:
        raise InvalidCellAddress("Cell address must use A1 notation")
    column_letters, row_text = match.groups()
    column_index = 0
    for character in column_letters.upper():
        column_index = column_index * 26 + (ord(character) - ord("A") + 1)
    row_index = int(row_text)
    if column_index > _MAX_EXCEL_COLUMN or row_index > _MAX_EXCEL_ROW:
        raise InvalidCellAddress("Cell address is outside Excel worksheet bounds")
    return f"{column_letters.upper()}{row_index}"


def _formula_backed(exact_formula: str | None, formula_status: str) -> bool:
    return bool(exact_formula) or formula_status.startswith("formula")


def _canonical_value_type(value: object, data_type: str | None) -> str | None:
    if value is None:
        return "blank"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (datetime, date)) or data_type == "d":
        return "date"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return "number"
    if isinstance(value, str):
        return "text"
    return None
