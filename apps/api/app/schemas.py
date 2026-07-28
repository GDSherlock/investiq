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

_MAX_CALCULATION_NUMBER_LITERAL_LENGTH = 128
_MAX_CALCULATION_NUMBER_SIGNIFICANT_DIGITS = 32
_MIN_BINARY64_DECIMAL_EXPONENT = -324
_MAX_BINARY64_DECIMAL_EXPONENT = 308
_MAX_CALCULATION_NUMBER_SCALE = (
    -_MIN_BINARY64_DECIMAL_EXPONENT
    + _MAX_CALCULATION_NUMBER_SIGNIFICANT_DIGITS
    - 1
)


class _CalculationDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class CalculationNumberValue(_CalculationDTO):
    value_type: Literal["number"]
    value: StrictStr

    @field_validator("value")
    @classmethod
    def validate_finite_decimal(cls, value: str) -> str:
        if len(value) > _MAX_CALCULATION_NUMBER_LITERAL_LENGTH:
            raise ValueError("Number value literal is too long")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Number value must be a decimal string") from exc
        if not decimal_value.is_finite():
            raise ValueError("Number value must be finite")
        _sign, digits, exponent = decimal_value.as_tuple()
        if len(digits) > _MAX_CALCULATION_NUMBER_SIGNIFICANT_DIGITS:
            raise ValueError("Number value has too many significant digits")
        decimal_exponent = int(exponent)
        if (
            decimal_exponent > _MAX_BINARY64_DECIMAL_EXPONENT
            or decimal_exponent < -_MAX_CALCULATION_NUMBER_SCALE
        ):
            raise ValueError(
                "Number value exponent is outside the calculation engine range"
            )
        if decimal_value != 0 and not (
            _MIN_BINARY64_DECIMAL_EXPONENT
            <= decimal_value.adjusted()
            <= _MAX_BINARY64_DECIMAL_EXPONENT
        ):
            raise ValueError(
                "Number value exponent is outside the calculation engine range"
            )
        try:
            float_value = float(decimal_value)
        except (OverflowError, ValueError):
            raise ValueError(
                "Number value is outside the calculation engine range"
            ) from None
        if not math.isfinite(float_value):
            raise ValueError("Number value is outside the calculation engine range")
        if decimal_value != 0 and float_value == 0.0:
            raise ValueError("Number value underflows the calculation engine range")
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


class CalculationOutputSourceItem(_CalculationDTO):
    sheet_name: str
    cell_address: str
    formula_cell_id: UUIDString | None = None
    formula_status: str
    number_format: str | None = None


class CalculationOutputPointItem(_CalculationDTO):
    financial_series_value_id: UUIDString
    period_index: int
    period: str | None = None
    formula_cell_id: UUIDString | None = None
    mapping_status: Literal["mapped", "missing", "static"]
    support_status: str
    source_sheet: str
    source_cell: str
    formula_status: str
    number_format: str | None = None


class CalculationOutputDefinitionItem(_CalculationDTO):
    output_id: UUIDString
    entity_kind: Literal["scalar", "series"]
    business_role: str
    label: str
    unit: str | None = None
    scenario: str | None = None
    mapping_status: Literal["mapped", "partial", "missing", "static"]
    support_status: str
    source: CalculationOutputSourceItem | None = None
    points: list[CalculationOutputPointItem] = Field(default_factory=list)


class CalculationOutputsResponse(_CalculationDTO):
    model_version_id: UUIDString
    outputs: list[CalculationOutputDefinitionItem] = Field(default_factory=list)


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


class CalculationProjectedValueItem(_CalculationDTO):
    availability_status: Literal["available", "unavailable"]
    value: CalculationOutputValue | None = None
    unavailable_reason: str | None = None
    execution_status: str | None = None
    engine_error_code: str | None = None
    validation_status: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CalculationRunScalarOutputItem(_CalculationDTO):
    output_id: UUIDString
    entity_kind: Literal["scalar"]
    business_role: str
    label: str
    unit: str | None = None
    scenario: str | None = None
    formula_cell_id: UUIDString | None = None
    mapping_status: Literal["mapped", "partial", "missing", "static"]
    support_status: str
    number_format: str | None = None
    availability_status: Literal["available", "partial", "unavailable"]
    baseline: CalculationProjectedValueItem
    current: CalculationProjectedValueItem


class CalculationRunSeriesPointItem(_CalculationDTO):
    financial_series_value_id: UUIDString
    period_index: int
    period: str | None = None
    formula_cell_id: UUIDString | None = None
    mapping_status: Literal["mapped", "missing", "static"]
    support_status: str
    number_format: str | None = None
    availability_status: Literal["available", "partial", "unavailable"]
    baseline: CalculationProjectedValueItem
    current: CalculationProjectedValueItem


class CalculationRunSeriesOutputItem(_CalculationDTO):
    output_id: UUIDString
    entity_kind: Literal["series"]
    business_role: str
    label: str
    unit: str | None = None
    scenario: str | None = None
    mapping_status: Literal["mapped", "partial", "missing", "static"]
    support_status: str
    availability_status: Literal["available", "partial", "unavailable"]
    points: list[CalculationRunSeriesPointItem] = Field(default_factory=list)


CalculationRunOutputItem = Annotated[
    CalculationRunScalarOutputItem | CalculationRunSeriesOutputItem,
    Field(discriminator="entity_kind"),
]


class CalculationRunOutputsResponse(_CalculationDTO):
    calculation_run_id: UUIDString
    model_version_id: UUIDString
    graph_version_id: UUIDString
    base_run_id: UUIDString | None = None
    comparison_baseline_run_id: UUIDString
    outputs: list[CalculationRunOutputItem] = Field(default_factory=list)


class SemanticBindingEntityItem(_CalculationDTO):
    entity_kind: Literal["canonical_output", "financial_series", "model_parameter"]
    entity_id: UUIDString
    label: str
    business_role: str | None = None
    unit: str | None = None


class SemanticBindingSlotItem(_CalculationDTO):
    semantic_role: str
    status: Literal[
        "unresolved",
        "candidate",
        "ambiguous",
        "extracted",
        "reviewed",
    ]
    binding: SemanticBindingEntityItem | None = None
    candidates: list[SemanticBindingEntityItem] = Field(default_factory=list)


class SemanticBindingsPreviewResponse(_CalculationDTO):
    model_version_id: UUIDString
    slots: list[SemanticBindingSlotItem] = Field(default_factory=list)


class SemanticBindingReviewRequest(_CalculationDTO):
    entity_kind: Literal["canonical_output", "financial_series", "model_parameter"]
    entity_id: UUIDString


class ParameterAnalysisReviewRequest(_CalculationDTO):
    business_role: Literal[
        "discount_rate",
        "project_irr_hurdle",
        "equity_irr_hurdle",
        "dscr_covenant",
        "debt_ratio",
        "equity_ratio",
    ] | None = None
    stochastic_eligible: StrictBool


class ParameterAnalysisReviewResponse(_CalculationDTO):
    model_version_id: UUIDString
    parameter_id: UUIDString
    business_role: str | None = None
    stochastic_eligible: bool


class AnalysisBenchmarkItem(_CalculationDTO):
    role: str
    value: str
    display_value: str
    source_ids: list[UUIDString] = Field(default_factory=list)


class AnalysisKpiItem(_CalculationDTO):
    slot: str
    role: str
    label: str
    value: str | None = None
    unit: str | None = None
    display_value: str
    benchmark: AnalysisBenchmarkItem | None = None
    status: str
    source_type: Literal["calculated", "derived", "unavailable"]
    availability_status: Literal["available", "partial", "unavailable"]
    quality_status: str
    validation_status: str | None = None
    calculation_run_id: UUIDString
    source_ids: list[UUIDString] = Field(default_factory=list)


class AnalysisSeriesPointItem(_CalculationDTO):
    period_index: int
    period: str | None = None
    value: str | None = None
    availability_status: Literal["available", "unavailable"]
    validation_status: str | None = None
    source_ids: list[UUIDString] = Field(default_factory=list)


class AnalysisSeriesItem(_CalculationDTO):
    role: str
    label: str
    unit: str | None = None
    source_type: Literal["calculated", "derived"]
    availability_status: Literal["available", "partial", "unavailable"]
    source_ids: list[UUIDString] = Field(default_factory=list)
    points: list[AnalysisSeriesPointItem] = Field(default_factory=list)


class AnalysisChartItem(_CalculationDTO):
    slot: str
    title: str
    availability_status: Literal["available", "partial", "unavailable"]
    source_type: Literal["calculated", "derived", "unavailable"]
    fallback_used: str | None = None
    series: list[AnalysisSeriesItem] = Field(default_factory=list)


class OverviewAnalysisResponse(_CalculationDTO):
    calculation_run_id: UUIDString
    model_version_id: UUIDString
    graph_version_id: UUIDString
    kpis: list[AnalysisKpiItem] = Field(default_factory=list)
    charts: list[AnalysisChartItem] = Field(default_factory=list)


class CashFlowAnalysisResponse(_CalculationDTO):
    calculation_run_id: UUIDString
    model_version_id: UUIDString
    graph_version_id: UUIDString
    charts: list[AnalysisChartItem] = Field(default_factory=list)


class ModelDiagnosticsResponse(_CalculationDTO):
    model_version_id: UUIDString
    status: str
    validation_status: str
    submitted: bool
    stop_reason: str | None = None
    error_code: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    validation_summary: dict[str, Any] = Field(default_factory=dict)
    time_series_summary: dict[str, Any] = Field(default_factory=dict)
    detected_sheets: list[str] = Field(default_factory=list)
    error_count: int = 0


MonteCarloDistributionFamily = Literal[
    "normal",
    "triangular",
    "uniform",
    "lognormal",
    "discrete",
]
MonteCarloOutputRole = Literal[
    "project_irr",
    "equity_irr",
    "project_npv",
    "equity_npv",
    "minimum_dscr",
]


class MonteCarloInputConfigurationItem(_CalculationDTO):
    parameter_id: UUIDString
    distribution_type: MonteCarloDistributionFamily
    distribution_parameters: dict[str, Any]

    @model_validator(mode="after")
    def validate_distribution_parameters(
        self,
    ) -> "MonteCarloInputConfigurationItem":
        from .monte_carlo_engine import validate_distribution

        validate_distribution(
            self.distribution_type,
            self.distribution_parameters,
        )
        return self


class MonteCarloRunCreateRequest(_CalculationDTO):
    graph_version_id: UUIDString
    baseline_calculation_run_id: UUIDString
    current_calculation_run_id: UUIDString
    trial_count: int = Field(ge=1, le=50_000)
    random_seed: int
    inputs: list[MonteCarloInputConfigurationItem] = Field(
        min_length=1,
        max_length=32,
    )
    correlation_matrix: list[list[float]]
    selected_output_roles: list[MonteCarloOutputRole] = Field(
        min_length=1,
        max_length=5,
    )
    idempotency_key: StrictStr = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_configuration(self) -> "MonteCarloRunCreateRequest":
        from .monte_carlo_engine import validate_correlation_matrix

        parameter_ids = [item.parameter_id for item in self.inputs]
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("Duplicate Monte Carlo parameter")
        if len(self.selected_output_roles) != len(
            set(self.selected_output_roles)
        ):
            raise ValueError("Duplicate Monte Carlo output role")
        validate_correlation_matrix(
            self.correlation_matrix,
            len(self.inputs),
        )
        return self


class MonteCarloEligibleInputItem(_CalculationDTO):
    parameter_id: UUIDString
    business_role: str | None = None
    label: str
    unit: str | None = None
    current_value: str


class MonteCarloInputCatalogResponse(_CalculationDTO):
    model_version_id: UUIDString
    graph_version_id: UUIDString
    inputs: list[MonteCarloEligibleInputItem] = Field(default_factory=list)
    supported_distribution_types: list[
        MonteCarloDistributionFamily
    ] = Field(default_factory=list)
    supported_output_roles: list[MonteCarloOutputRole] = Field(
        default_factory=list
    )


class MonteCarloRunResponse(_CalculationDTO):
    monte_carlo_run_id: UUIDString
    model_version_id: UUIDString
    graph_version_id: UUIDString
    baseline_calculation_run_id: UUIDString
    current_calculation_run_id: UUIDString
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    trial_count: int
    random_seed: int
    method_version: str
    engine_version: str
    runtime_ms: int | None = None
    cancel_requested: bool
    input_configuration: dict[str, Any]
    result_artifact: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class MonteCarloRunHistoryResponse(_CalculationDTO):
    model_version_id: UUIDString
    runs: list[MonteCarloRunResponse] = Field(default_factory=list)


class CalculationSensitivityOverrideRequest(_CalculationDTO):
    target: CalculationOverrideTarget
    value: CalculationNumberValue


class CalculationSensitivityDriverRequest(_CalculationDTO):
    target: CalculationOverrideTarget
    low: CalculationNumberValue
    high: CalculationNumberValue

    @model_validator(mode="after")
    def reject_equal_endpoints(self) -> "CalculationSensitivityDriverRequest":
        if Decimal(self.low.value) == Decimal(self.high.value):
            raise ValueError("Driver low and high values must differ")
        return self


class CalculationSensitivityAxisRequest(_CalculationDTO):
    target: CalculationOverrideTarget
    values: list[CalculationNumberValue] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def reject_duplicate_values(self) -> "CalculationSensitivityAxisRequest":
        values = [Decimal(value.value) for value in self.values]
        if len(values) != len(set(values)):
            raise ValueError("Duplicate two-way axis value")
        return self


class CalculationSensitivityTwoWayRequest(_CalculationDTO):
    row: CalculationSensitivityAxisRequest
    column: CalculationSensitivityAxisRequest

    @model_validator(mode="after")
    def reject_same_axis_target(self) -> "CalculationSensitivityTwoWayRequest":
        if self.row.target.identity == self.column.target.identity:
            raise ValueError("Two-way axis targets must differ")
        return self


class CalculationSensitivityRequest(_CalculationDTO):
    graph_version_id: UUIDString
    output_id: UUIDString
    current_run_id: UUIDString | None = None
    two_way_mode: Literal["explicit", "top_impact"] = "explicit"
    current_overrides: list[CalculationSensitivityOverrideRequest] = Field(
        default_factory=list,
        max_length=500,
    )
    drivers: list[CalculationSensitivityDriverRequest] = Field(
        min_length=1,
        max_length=12,
    )
    two_way: CalculationSensitivityTwoWayRequest | None = None

    @model_validator(mode="after")
    def validate_sensitivity_shape(self) -> "CalculationSensitivityRequest":
        override_targets = [
            override.target.identity for override in self.current_overrides
        ]
        if len(override_targets) != len(set(override_targets)):
            raise ValueError("Duplicate current override target")
        driver_targets = [driver.target.identity for driver in self.drivers]
        if len(driver_targets) != len(set(driver_targets)):
            raise ValueError("Duplicate one-way driver target")
        if self.two_way_mode == "top_impact":
            if self.two_way is not None:
                raise ValueError(
                    "Top-impact two-way mode does not accept explicit axes"
                )
            two_way_cases = 25
        else:
            two_way_cases = (
                len(self.two_way.row.values) * len(self.two_way.column.values)
                if self.two_way is not None
                else 0
            )
        case_count = 1 + 2 * len(self.drivers) + two_way_cases
        if case_count > 50:
            raise ValueError("Sensitivity requests support at most 50 cases")
        return self


class CalculationSensitivitySelectedOutput(_CalculationDTO):
    output_id: UUIDString
    business_role: str
    label: str
    unit: str | None = None
    scenario: str | None = None
    number_format: str | None = None
    mapping_status: Literal["mapped", "partial", "missing", "static"]
    support_status: str
    availability_status: Literal["available", "partial", "unavailable"]
    baseline: CalculationProjectedValueItem
    current: CalculationProjectedValueItem


class CalculationSensitivityCaseOutput(_CalculationDTO):
    output_id: UUIDString
    business_role: str
    label: str
    unit: str | None = None
    scenario: str | None = None
    number_format: str | None = None
    value: CalculationProjectedValueItem


class CalculationSensitivityCase(_CalculationDTO):
    case_id: UUIDString | None = None
    input_value: CalculationNumberValue
    calculation_run_id: UUIDString | None
    output: CalculationProjectedValueItem
    outputs: list[CalculationSensitivityCaseOutput] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)


class CalculationSensitivityDriverResult(_CalculationDTO):
    target: CalculationOverrideTarget
    low_case: CalculationSensitivityCase
    high_case: CalculationSensitivityCase
    impact: StrictStr | None = None
    warnings: list[str] = Field(default_factory=list)


class CalculationSensitivityTwoWayCell(_CalculationDTO):
    case_id: UUIDString | None = None
    row_value: CalculationNumberValue
    column_value: CalculationNumberValue
    calculation_run_id: UUIDString | None
    output: CalculationProjectedValueItem
    outputs: list[CalculationSensitivityCaseOutput] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)


class CalculationSensitivityTwoWayResult(_CalculationDTO):
    row_target: CalculationOverrideTarget
    column_target: CalculationOverrideTarget
    cells: list[CalculationSensitivityTwoWayCell]


class CalculationSensitivityResponse(_CalculationDTO):
    analysis_id: UUIDString | None = None
    request_hash: StrictStr | None = None
    case_count: int = 0
    model_version_id: UUIDString
    graph_version_id: UUIDString
    comparison_baseline_run_id: UUIDString
    current_run_id: UUIDString
    selected_output: CalculationSensitivitySelectedOutput
    current_outputs: list[CalculationSensitivityCaseOutput] = Field(
        default_factory=list
    )
    drivers: list[CalculationSensitivityDriverResult]
    two_way: CalculationSensitivityTwoWayResult | None = None
    warnings: list[str] = Field(default_factory=list)


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
