export type CalculationReadinessStatus =
  | 'model_not_ready'
  | 'not_prepared'
  | 'preparing'
  | 'ready'
  | 'ready_with_warning'
  | 'failed';

export type CalculationUiPhase =
  | 'idle'
  | 'uploading'
  | 'uploaded'
  | 'checking_readiness'
  | 'not_prepared'
  | 'preparing'
  | 'loading_inputs'
  | 'running_baseline'
  | 'ready_for_override'
  | 'running_override'
  | 'completed'
  | 'failed';

export type CalculationTypedValue =
  | { value_type: 'number'; value: string }
  | { value_type: 'boolean'; value: boolean }
  | { value_type: 'text'; value: string }
  | { value_type: 'blank'; value: null }
  | { value_type: 'date'; value: string }
  | {
      value_type: 'date_serial';
      value: string;
      iso_evidence?: string | null;
    }
  | { value_type: 'error'; error_code: string };

export type CalculationInputValue = Extract<
  CalculationTypedValue,
  { value_type: 'number' | 'boolean' | 'text' | 'blank' | 'date' }
>;

export interface WorkbookValidationResponse {
  workbook_version_id: string | null;
  model_version_id: string | null;
  endpoint_mode: string;
  filename: string;
  runtime_seconds: number;
  driver_meta: Record<string, unknown>;
  submitted: boolean;
  stop_reason: string;
  coverage: Record<string, unknown>;
  final_extraction: Record<string, unknown>;
  validation_summary: Record<string, number>;
  time_series_summary: Record<string, number>;
  validation_results: Record<string, unknown>[];
  warnings: Record<string, unknown>[];
  errors: Record<string, unknown>[];
  trace: Record<string, unknown>[];
  trace_truncated: boolean;
}

export interface CalculationErrorDetail {
  code: string;
  message: string;
  retryable: boolean;
  resource_id: string | null;
}

export class CalculationApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly resourceId: string | null;
  readonly detail: CalculationErrorDetail;

  constructor(status: number, detail: CalculationErrorDetail) {
    super(detail.message);
    this.name = 'CalculationApiError';
    this.status = status;
    this.code = detail.code;
    this.retryable = detail.retryable;
    this.resourceId = detail.resource_id;
    this.detail = detail;
  }
}

export interface CalculationReadinessVersions {
  phase1_ir: string;
  phase2_ir: string;
  compiler: string;
  engine: string;
  registry: string;
  semantics: string;
}

export interface CalculationReadinessSummary {
  formula_cells_total: number;
  formula_cells_supported: number;
  graph_nodes: number;
  graph_edges: number;
}

export interface CalculationReadinessResponse {
  model_version_id: string;
  workbook_version_id: string;
  model_status: string;
  validation_status: string;
  status: CalculationReadinessStatus;
  calculation_rule_extraction_id: string | null;
  graph_version_id: string | null;
  versions: CalculationReadinessVersions;
  summary: CalculationReadinessSummary;
  warnings: string[];
  error: CalculationErrorDetail | null;
}

export interface CalculationInput {
  target_kind: 'parameter' | 'financial_series_value';
  target_id: string;
  label: string;
  category: string | null;
  unit: string | null;
  scenario: string | null;
  period: string | null;
  current_value: CalculationInputValue;
  editable: boolean;
  non_editable_reason: string | null;
}

export interface CalculationInputsResponse {
  model_version_id: string;
  graph_version_id: string;
  inputs: CalculationInput[];
  next_cursor: string | null;
}

export type CalculationOutputMappingStatus =
  | 'mapped'
  | 'partial'
  | 'missing'
  | 'static';

export type CalculationOutputAvailabilityStatus =
  | 'available'
  | 'partial'
  | 'unavailable';

export type CalculationOutputValue = Exclude<
  CalculationTypedValue,
  { value_type: 'date' }
>;

export interface CalculationProjectedOutputValue {
  availability_status: 'available' | 'unavailable';
  value: CalculationOutputValue | null;
  unavailable_reason: string | null;
  execution_status: string | null;
  engine_error_code: string | null;
  validation_status: string | null;
  warnings: string[];
}

export interface CalculationRunScalarOutput {
  output_id: string;
  entity_kind: 'scalar';
  business_role: string;
  label: string;
  unit: string | null;
  scenario: string | null;
  formula_cell_id: string | null;
  mapping_status: CalculationOutputMappingStatus;
  support_status: string;
  number_format: string | null;
  availability_status: CalculationOutputAvailabilityStatus;
  baseline: CalculationProjectedOutputValue;
  current: CalculationProjectedOutputValue;
}

export interface CalculationRunSeriesPoint {
  financial_series_value_id: string;
  period_index: number;
  period: string | null;
  formula_cell_id: string | null;
  mapping_status: Exclude<CalculationOutputMappingStatus, 'partial'>;
  support_status: string;
  number_format: string | null;
  availability_status: CalculationOutputAvailabilityStatus;
  baseline: CalculationProjectedOutputValue;
  current: CalculationProjectedOutputValue;
}

export interface CalculationRunSeriesOutput {
  output_id: string;
  entity_kind: 'series';
  business_role: string;
  label: string;
  unit: string | null;
  scenario: string | null;
  mapping_status: CalculationOutputMappingStatus;
  support_status: string;
  availability_status: CalculationOutputAvailabilityStatus;
  points: CalculationRunSeriesPoint[];
}

export type CalculationRunOutput =
  | CalculationRunScalarOutput
  | CalculationRunSeriesOutput;

export interface CalculationRunOutputsResponse {
  calculation_run_id: string;
  model_version_id: string;
  graph_version_id: string;
  base_run_id: string | null;
  comparison_baseline_run_id: string;
  outputs: CalculationRunOutput[];
}

export type CalculationOverrideTarget =
  | { kind: 'parameter'; parameter_id: string }
  | {
      kind: 'financial_series_value';
      financial_series_value_id: string;
    };

export interface CalculationOverride {
  target: CalculationOverrideTarget;
  value: CalculationInputValue;
}

export interface CalculationRequest {
  graph_version_id: string;
  overrides: CalculationOverride[];
  idempotency_key: string | null;
}

export type CalculationNumberValue = Extract<
  CalculationTypedValue,
  { value_type: 'number' }
>;

export interface CalculationSensitivityOverrideRequest {
  target: CalculationOverrideTarget;
  value: CalculationNumberValue;
}

export interface CalculationSensitivityDriverRequest {
  target: CalculationOverrideTarget;
  low: CalculationNumberValue;
  high: CalculationNumberValue;
}

export interface CalculationSensitivityAxisRequest {
  target: CalculationOverrideTarget;
  values: CalculationNumberValue[];
}

export interface CalculationSensitivityTwoWayRequest {
  row: CalculationSensitivityAxisRequest;
  column: CalculationSensitivityAxisRequest;
}

export interface CalculationSensitivityRequest {
  graph_version_id: string;
  output_id: string;
  current_overrides: CalculationSensitivityOverrideRequest[];
  drivers: CalculationSensitivityDriverRequest[];
  two_way: CalculationSensitivityTwoWayRequest | null;
}

export interface CalculationSensitivitySelectedOutput {
  output_id: string;
  business_role: string;
  label: string;
  unit: string | null;
  scenario: string | null;
  number_format: string | null;
  mapping_status: CalculationOutputMappingStatus;
  support_status: string;
  availability_status: CalculationOutputAvailabilityStatus;
  baseline: CalculationProjectedOutputValue;
  current: CalculationProjectedOutputValue;
}

export interface CalculationSensitivityCase {
  input_value: CalculationNumberValue;
  calculation_run_id: string;
  output: CalculationProjectedOutputValue;
  warnings: string[];
}

export interface CalculationSensitivityDriverResult {
  target: CalculationOverrideTarget;
  low_case: CalculationSensitivityCase;
  high_case: CalculationSensitivityCase;
  impact: string | null;
  warnings: string[];
}

export interface CalculationSensitivityTwoWayCell {
  row_value: CalculationNumberValue;
  column_value: CalculationNumberValue;
  calculation_run_id: string;
  output: CalculationProjectedOutputValue;
  warnings: string[];
}

export interface CalculationSensitivityTwoWayResult {
  row_target: CalculationOverrideTarget;
  column_target: CalculationOverrideTarget;
  cells: CalculationSensitivityTwoWayCell[];
}

export interface CalculationSensitivityResponse {
  model_version_id: string;
  graph_version_id: string;
  comparison_baseline_run_id: string;
  current_run_id: string;
  selected_output: CalculationSensitivitySelectedOutput;
  drivers: CalculationSensitivityDriverResult[];
  two_way: CalculationSensitivityTwoWayResult | null;
  warnings: string[];
}

export interface CalculationRunSummary {
  formula_cells_total: number;
  formula_cells_supported: number;
  unsupported_formula_cells: number;
  calculated_formula_cells: number;
  reused_formula_cells: number;
  dirty_formula_cells: number;
  cycle_formula_cells: number;
  blocked_formula_cells: number;
  execution_error_cells: number;
  grouped_calculation_rules: number;
  graph_nodes: number;
  graph_edges: number;
}

export interface CalculationRunVersions {
  phase2_ir: string;
  compiler: string;
  engine: string;
  registry: string;
  semantics: string;
}

export interface CalculationRunValue {
  formula_cell_id: string;
  sheet_name: string;
  cell_address: string;
  status: string;
  value: CalculationTypedValue | null;
  engine_error_code: string | null;
  reused_from_run_id: string | null;
  validation_status: string;
  warnings: string[];
}

export interface CalculationRunResponse {
  calculation_run_id: string;
  model_version_id: string;
  graph_version_id: string;
  base_run_id: string | null;
  status:
    | 'pending'
    | 'running'
    | 'completed'
    | 'completed_with_warning'
    | 'failed'
    | 'cancelled';
  versions: CalculationRunVersions;
  summary: CalculationRunSummary;
  warnings: string[];
  values: CalculationRunValue[];
}
