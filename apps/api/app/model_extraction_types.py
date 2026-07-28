"""Shared value types and sanitized errors for Model Extraction persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
import uuid


BUSINESS_OUTPUT_ROLES = (
    "project_irr",
    "equity_irr",
    "npv",
    "minimum_dscr",
    "average_dscr",
    "total_project_cost",
    "total_capex",
    "total_debt",
    "peak_debt",
    "average_ebitda_margin",
    "payback_period",
    "equity_multiple",
    "revenue",
    "opex",
    "fixed_opex",
    "variable_opex",
    "ebitda",
    "cfads",
    "debt_service",
    "debt_balance",
    "opening_debt",
    "closing_debt",
    "principal_repayment",
    "interest_expense",
    "cash_flow",
    "project_free_cash_flow",
    "equity_cash_flow",
    "operating_cash_flow",
    "dscr",
    "dscr_covenant",
    "capex",
    "total_equity",
    "debt_ratio",
    "equity_ratio",
    "debt_to_equity_ratio",
    "tax",
    "net_generation",
    "power_price",
    "unclassified",
)

BUSINESS_PARAMETER_ROLES = (
    "discount_rate",
    "project_irr_hurdle",
    "equity_irr_hurdle",
    "dscr_covenant",
    "debt_ratio",
    "equity_ratio",
)

SEMANTIC_BINDING_ROLES = (
    "project_irr",
    "equity_irr",
    "project_npv",
    "equity_npv",
    "payback_period",
    "minimum_dscr",
    "average_dscr",
    "equity_multiple",
    "debt_to_equity_ratio",
    "discount_rate",
    "project_irr_hurdle",
    "equity_irr_hurdle",
    "dscr_covenant",
    "revenue",
    "ebitda",
    "cfads",
    "project_free_cash_flow",
    "equity_cash_flow",
    "operating_cash_flow",
    "debt_service",
    "dscr",
    "closing_debt",
    "capex",
    "interest_expense",
    "principal_repayment",
    "total_debt",
    "total_equity",
    "debt_ratio",
    "equity_ratio",
)


class ModelExtractionPersistenceError(RuntimeError):
    """Base error for persistence operations safe to translate at an API boundary."""


class WorkbookIntegrityError(ModelExtractionPersistenceError):
    """Stored workbook bytes do not match their immutable catalog metadata."""


class WorkbookVersionNotFound(ModelExtractionPersistenceError):
    """The requested workbook version or storage location does not exist."""


class WorkbookTooLargeError(ModelExtractionPersistenceError):
    """The uploaded workbook exceeds the configured pre-extraction byte limit."""

    def __init__(self, actual_bytes: int, max_bytes: int):
        self.actual_bytes = actual_bytes
        self.max_bytes = max_bytes
        super().__init__("Workbook exceeds the configured upload size limit")


class ModelVersionNotFound(ModelExtractionPersistenceError):
    """The requested model version does not exist."""


class CanonicalPersistenceStateError(ModelExtractionPersistenceError):
    """Canonical rows cannot be written from the model version's current state."""


class ModelVersionNotReady(ModelExtractionPersistenceError):
    """The model version exists but is not canonically materialized."""

    def __init__(self, status: str):
        self.status = status
        super().__init__(f"Model version is not ready: {status}")


class ModelWorkbookMismatch(ModelExtractionPersistenceError):
    """The supplied model and workbook version IDs do not belong together."""


class FinancialSeriesNotFound(ModelExtractionPersistenceError):
    """The requested financial series is not part of the model version."""


class ParameterNotFound(ModelExtractionPersistenceError):
    """The requested canonical parameter is not part of the model version."""


class FinancialSeriesValueNotFound(ModelExtractionPersistenceError):
    """The requested canonical series value is not part of the model version."""


class InvalidCellAddress(ModelExtractionPersistenceError):
    """A source cell is not a valid bounded Excel A1 address."""


class AmbiguousSourceCellError(ModelExtractionPersistenceError):
    """More than one canonical entity maps to the same source cell."""


class CanonicalSourceConflictError(ModelExtractionPersistenceError):
    """Source-valid candidates disagree at one canonical workbook cell."""


class PersistenceRetryNotAllowed(ModelExtractionPersistenceError):
    """The model lifecycle does not permit persistence-only retry."""


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

    def output_id(self, source_sheet: str, source_cell: str) -> str:
        key = "|".join(
            [
                "financial_entity",
                "output",
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


@dataclass(frozen=True)
class WorkbookVersionData:
    id: str
    sha256: str
    original_filename: str
    file_size: int
    created_at: datetime
    content_bytes: bytes


@dataclass(frozen=True)
class ModelVersionData:
    id: str
    workbook_version_id: str
    upload_filename: str
    status: str
    validation_status: str
    submitted: bool
    stop_reason: str | None
    created_at: datetime
    extracted_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class CanonicalParameter:
    id: str
    model_version_id: str
    entity_kind: Literal["parameter"]
    llm_candidate_alias: str | None
    source_bucket: str
    label: str
    category: str | None
    canonical_name: str | None
    submitted_role: str
    validated_role: str
    raw_value_json: Any
    validated_value_json: Any
    unit: str | None
    scenario: str | None
    period_json: Any
    source_sheet: str
    source_cell: str
    exact_formula: str | None
    formula_status: str
    source_validation_status: str
    role_validation_status: str
    validation_status: str
    data_type: str | None
    number_format: str | None
    llm_confidence: float | None
    validation_confidence: float | None
    reasoning_summary: str | None
    validation_warnings_json: list[Any] | None
    created_at: datetime

    @property
    def entity_ref(self) -> FinancialEntityRef:
        return FinancialEntityRef(
            id=self.id,
            model_version_id=self.model_version_id,
            entity_kind=self.entity_kind,
            label=self.label,
        )


@dataclass(frozen=True)
class CanonicalFinancialSeries:
    id: str
    model_version_id: str
    entity_kind: Literal["financial_series"]
    llm_series_alias: str | None
    label: str
    category: str | None
    semantic_role: str
    business_role: str | None
    unit: str | None
    frequency: str | None
    orientation: str
    scenario: str | None
    entity: str | None
    currency: str | None
    calculation_type: str
    period_source_range: str
    value_source_range: str
    label_source_sheet: str | None
    label_source_cell: str | None
    materialization_status: str
    validation_status: str
    aliases_json: list[Any] | None
    formula_pattern_json: dict[str, Any] | None
    warnings_json: list[Any] | None
    reasoning_summary: str | None
    llm_confidence: float | None
    created_at: datetime

    @property
    def entity_ref(self) -> FinancialEntityRef:
        return FinancialEntityRef(
            id=self.id,
            model_version_id=self.model_version_id,
            entity_kind=self.entity_kind,
            label=self.label,
        )


@dataclass(frozen=True)
class CanonicalFinancialSeriesValue:
    id: str
    financial_series_id: str
    period_index: int
    raw_period_label_json: Any
    display_period_label: str | None
    period_type: str | None
    year: int | None
    quarter: int | None
    month: int | None
    is_forecast: bool | None
    value_json: Any
    period_source_sheet: str
    period_source_cell: str
    value_source_sheet: str
    value_source_cell: str
    exact_formula: str | None
    formula_status: str
    cached_value_available: bool
    cached_value_freshness: str | None
    number_format: str | None
    data_type: str | None
    created_at: datetime


@dataclass(frozen=True)
class CalculationOutputSource:
    sheet_name: str
    cell_address: str
    formula_cell_id: str | None
    formula_status: str
    number_format: str | None


@dataclass(frozen=True)
class CalculationOutputPoint:
    financial_series_value_id: str
    period_index: int
    period: str | None
    formula_cell_id: str | None
    mapping_status: Literal["mapped", "missing", "static"]
    support_status: str
    source_sheet: str
    source_cell: str
    formula_status: str
    number_format: str | None


@dataclass(frozen=True)
class CalculationOutputDefinition:
    output_id: str
    entity_kind: Literal["scalar", "series"]
    business_role: str
    label: str
    unit: str | None
    scenario: str | None
    mapping_status: Literal["mapped", "partial", "missing", "static"]
    support_status: str
    source: CalculationOutputSource | None
    points: tuple[CalculationOutputPoint, ...] = ()


@dataclass(frozen=True)
class CanonicalCalculationInput:
    target_kind: Literal["parameter", "financial_series_value"]
    target_id: str
    model_version_id: str
    label: str
    category: str | None
    unit: str | None
    scenario: str | None
    period: str | None
    current_value: Any
    value_type: str | None
    source_sheet: str
    source_cell: str
    formula_backed: bool
    source_owner_count: int

    @property
    def editable(self) -> bool:
        return self.non_editable_reason is None

    @property
    def non_editable_reason(self) -> str | None:
        if self.formula_backed:
            return "formula_backed"
        if self.source_owner_count != 1:
            return "ambiguous_source_ownership"
        if self.value_type not in {"number", "boolean", "text", "blank", "date"}:
            return "unsupported_value_type"
        return None


FinancialEntity = CanonicalParameter | CanonicalFinancialSeries


@dataclass(frozen=True)
class ParameterResolution:
    entity: FinancialEntityRef
    parameter: CanonicalParameter


@dataclass(frozen=True)
class FinancialSeriesValueResolution:
    entity: FinancialEntityRef
    series: CanonicalFinancialSeries
    value: CanonicalFinancialSeriesValue


SourceResolvedEntity = ParameterResolution | FinancialSeriesValueResolution


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
