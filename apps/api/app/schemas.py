"""Pydantic schemas for API request/response validation."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
from typing import Annotated, Any, Literal, Optional
import uuid

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)


# Coerce UUID objects to strings
StrFromUUID = Annotated[str, BeforeValidator(lambda v: str(v) if v is not None else v)]


def _validated_uuid_string(value: str) -> str:
    return str(uuid.UUID(value))


UUIDString = Annotated[
    str,
    BeforeValidator(lambda value: str(value) if isinstance(value, uuid.UUID) else value),
    AfterValidator(_validated_uuid_string),
]


class _CalculationDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class CalculationNumberValue(_CalculationDTO):
    value_type: Literal["number"]
    value: StrictStr

    @field_validator("value")
    @classmethod
    def validate_finite_decimal(cls, value: str) -> str:
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Number value must be a decimal string") from exc
        if not decimal_value.is_finite():
            raise ValueError("Number value must be finite")
        try:
            finite_float = math.isfinite(float(decimal_value))
        except (OverflowError, ValueError):
            finite_float = False
        if not finite_float:
            raise ValueError("Number value is outside the calculation engine range")
        return value


class CalculationBooleanValue(_CalculationDTO):
    value_type: Literal["boolean"]
    value: StrictBool


class CalculationTextValue(_CalculationDTO):
    value_type: Literal["text"]
    value: StrictStr

    @field_validator("value")
    @classmethod
    def reject_formula_text(cls, value: str) -> str:
        if value.startswith("="):
            raise ValueError("Formula-like text is not allowed")
        return value


class CalculationBlankValue(_CalculationDTO):
    value_type: Literal["blank"]
    value: None


class CalculationDateValue(_CalculationDTO):
    value_type: Literal["date"]
    value: date


CalculationInputValue = Annotated[
    CalculationNumberValue
    | CalculationBooleanValue
    | CalculationTextValue
    | CalculationBlankValue
    | CalculationDateValue,
    Field(discriminator="value_type"),
]


class ParameterOverrideTarget(_CalculationDTO):
    kind: Literal["parameter"]
    parameter_id: UUIDString

    @property
    def identity(self) -> tuple[str, str]:
        return self.kind, self.parameter_id


class FinancialSeriesValueOverrideTarget(_CalculationDTO):
    kind: Literal["financial_series_value"]
    financial_series_value_id: UUIDString

    @property
    def identity(self) -> tuple[str, str]:
        return self.kind, self.financial_series_value_id


CalculationOverrideTarget = Annotated[
    ParameterOverrideTarget | FinancialSeriesValueOverrideTarget,
    Field(discriminator="kind"),
]


class CalculationOverrideRequest(_CalculationDTO):
    target: CalculationOverrideTarget
    value: CalculationInputValue


class CalculationRequest(_CalculationDTO):
    graph_version_id: UUIDString
    overrides: list[CalculationOverrideRequest] = Field(default_factory=list)
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def reject_duplicate_targets(self) -> "CalculationRequest":
        identities = [override.target.identity for override in self.overrides]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate override target")
        return self


class CalculationPrepareRequest(_CalculationDTO):
    pass


class CalculationErrorDetail(_CalculationDTO):
    code: str
    message: str
    retryable: bool
    resource_id: UUIDString | None = None


class CalculationReadinessVersions(_CalculationDTO):
    phase1_ir: str
    phase2_ir: str
    compiler: str
    engine: str
    registry: str
    semantics: str


class CalculationReadinessSummary(_CalculationDTO):
    formula_cells_total: int = 0
    formula_cells_supported: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0


class CalculationReadinessResponse(_CalculationDTO):
    model_version_id: UUIDString
    workbook_version_id: UUIDString
    model_status: str
    validation_status: str
    status: Literal[
        "model_not_ready",
        "not_prepared",
        "preparing",
        "ready",
        "ready_with_warning",
        "failed",
    ]
    calculation_rule_extraction_id: UUIDString | None = None
    graph_version_id: UUIDString | None = None
    versions: CalculationReadinessVersions
    summary: CalculationReadinessSummary
    warnings: list[str] = Field(default_factory=list)
    error: CalculationErrorDetail | None = None


class CalculationInputItem(_CalculationDTO):
    target_kind: Literal["parameter", "financial_series_value"]
    target_id: UUIDString
    label: str
    category: str | None = None
    unit: str | None = None
    scenario: str | None = None
    period: str | None = None
    current_value: CalculationInputValue
    editable: bool
    non_editable_reason: str | None = None


class CalculationInputsResponse(_CalculationDTO):
    model_version_id: UUIDString
    graph_version_id: UUIDString
    inputs: list[CalculationInputItem]
    next_cursor: UUIDString | None = None


class CalculationDateSerialValue(_CalculationDTO):
    value_type: Literal["date_serial"]
    value: StrictStr
    iso_evidence: str | None = None


class CalculationErrorValue(_CalculationDTO):
    value_type: Literal["error"]
    error_code: str


CalculationOutputValue = Annotated[
    CalculationNumberValue
    | CalculationBooleanValue
    | CalculationTextValue
    | CalculationBlankValue
    | CalculationDateSerialValue
    | CalculationErrorValue,
    Field(discriminator="value_type"),
]


class CalculationRunSummary(_CalculationDTO):
    formula_cells_total: int = 0
    formula_cells_supported: int = 0
    unsupported_formula_cells: int = 0
    calculated_formula_cells: int = 0
    reused_formula_cells: int = 0
    dirty_formula_cells: int = 0
    cycle_formula_cells: int = 0
    blocked_formula_cells: int = 0
    execution_error_cells: int = 0
    grouped_calculation_rules: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0


class CalculationRunVersions(_CalculationDTO):
    phase2_ir: str
    compiler: str
    engine: str
    registry: str
    semantics: str


class CalculationRunValueResponse(_CalculationDTO):
    formula_cell_id: UUIDString
    sheet_name: str
    cell_address: str
    status: str
    value: CalculationOutputValue | None
    engine_error_code: str | None = None
    reused_from_run_id: UUIDString | None = None
    validation_status: str
    warnings: list[str] = Field(default_factory=list)


class CalculationRunResponse(_CalculationDTO):
    calculation_run_id: UUIDString
    model_version_id: UUIDString
    graph_version_id: UUIDString
    base_run_id: UUIDString | None = None
    status: Literal[
        "pending",
        "running",
        "completed",
        "completed_with_warning",
        "failed",
        "cancelled",
    ]
    versions: CalculationRunVersions
    summary: CalculationRunSummary
    warnings: list[str] = Field(default_factory=list)
    values: list[CalculationRunValueResponse] = Field(default_factory=list)


# --- Model schemas ---
class ModelUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    model_id: StrFromUUID
    investment_id: StrFromUUID
    health_report: dict[str, Any]
    parsed_sheets: list[str]
    assumptions_count: int


class WorkbookValidationResponse(BaseModel):
    """Raw response for the experimental workbook-agent validation endpoint."""

    workbook_version_id: str | None
    model_version_id: str | None
    endpoint_mode: str
    filename: str
    runtime_seconds: float
    driver_meta: dict[str, Any]
    submitted: bool
    stop_reason: str
    coverage: dict[str, Any]
    final_extraction: dict[str, Any]
    validation_summary: dict[str, int]
    time_series_summary: dict[str, int]
    validation_results: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    trace_truncated: bool


class ModelParseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    model_id: StrFromUUID
    parsed_json: dict[str, Any]
    health_score: float


# --- Scenario schemas ---
class ScenarioCreate(BaseModel):
    model_id: str
    name: str
    assumptions_overrides: dict[str, Any] = Field(default_factory=dict)
    persona: Optional[str] = None


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: StrFromUUID
    model_id: StrFromUUID
    name: str
    assumptions_json: dict[str, Any] | None
    created_at: datetime | None


# --- Sensitivity schemas ---
class SensitivityRequest(BaseModel):
    variables: list[str] | None = None
    range_pct: float = 0.2


class SensitivityResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    scenario_id: StrFromUUID
    one_way: list[dict[str, Any]]
    two_way: dict[str, Any] | None = None
    ai_signal: dict[str, Any] | None = None


# --- Monte Carlo schemas ---
class MonteCarloRequest(BaseModel):
    n_simulations: int = 10000
    distribution: str = "normal"
    variables: dict[str, float] | None = None
    volatilities: dict[str, float] | None = None
    correlation_matrix: list[list[float]] | None = None


class MonteCarloResult(BaseModel):
    job_id: str
    status: str
    result: dict[str, Any] | None = None


# --- Cash Flow schemas ---
class CashFlowAnalysis(BaseModel):
    scenario_id: str
    unlevered_fcf: dict[str, Any]
    equity_fcf: dict[str, Any]
    p10_p50_p90: dict[str, float] | None = None
    covenant_status: dict[str, Any] | None = None


# --- Debt Analysis schemas ---
class DebtUploadResponse(BaseModel):
    job_id: str
    status: str


class DebtComparisonResult(BaseModel):
    job_id: str
    comparison: dict[str, Any]
    recommendation: dict[str, Any] | None = None


# --- Report schemas ---
class ReportGenerateRequest(BaseModel):
    investment_id: str
    report_type: str = "ic_paper"
    audience: str = "investment_committee"
    format: str = "markdown"


class ReportResponse(BaseModel):
    report_id: str
    status: str
    content: str | None = None


# --- Alert schemas ---
class AlertResponse(BaseModel):
    id: str
    investment_id: str
    alert_type: str
    threshold: float | None
    current_value: float | None
    severity: str
    message: str | None
    created_at: datetime | None


# --- Monitor schemas ---
class MonitorDashboard(BaseModel):
    investment_id: str
    kpis: dict[str, Any]
    dscr_status: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    variance_analysis: dict[str, Any] | None = None


# --- Audit schemas ---
class AuditEntry(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str | None
    user_id: str | None
    timestamp: datetime | None
    payload: dict[str, Any] | None
