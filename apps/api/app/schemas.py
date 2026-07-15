"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from typing import Any, Optional, Annotated
from pydantic import BaseModel, Field, ConfigDict, BeforeValidator


# Coerce UUID objects to strings
StrFromUUID = Annotated[str, BeforeValidator(lambda v: str(v) if v is not None else v)]


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
