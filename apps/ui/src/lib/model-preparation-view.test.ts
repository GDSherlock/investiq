import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPreparationNotifications,
  buildTechnicalDetails,
  formatSupportedPercentage,
  validateWorkbookFile,
} from './model-preparation-view';
import {
  CalculationApiError,
  type CalculationReadinessResponse,
  type CalculationRunResponse,
  type WorkbookValidationResponse,
} from './calculation-api-types';

function uploadResponse(
  overrides: Partial<WorkbookValidationResponse> = {},
): WorkbookValidationResponse {
  return {
    workbook_version_id: 'workbook-version',
    model_version_id: 'model-version',
    endpoint_mode: 'workbook_agent',
    filename: 'model.xlsx',
    runtime_seconds: 12.5,
    driver_meta: {},
    submitted: true,
    stop_reason: 'submitted',
    coverage: {},
    final_extraction: {},
    validation_summary: { validated: 1 },
    time_series_summary: {},
    validation_results: [],
    warnings: [],
    errors: [],
    trace: [],
    trace_truncated: false,
    ...overrides,
  };
}

function readinessResponse(
  overrides: Partial<CalculationReadinessResponse> = {},
): CalculationReadinessResponse {
  return {
    model_version_id: 'model-version',
    workbook_version_id: 'workbook-version',
    model_status: 'materialized',
    validation_status: 'validated_with_warning',
    status: 'ready_with_warning',
    calculation_rule_extraction_id: 'extraction-id',
    graph_version_id: 'graph-version',
    versions: {
      phase1_ir: '1',
      phase2_ir: '2',
      compiler: '3',
      engine: '4',
      registry: '5',
      semantics: '6',
    },
    summary: {
      formula_cells_total: 1043,
      formula_cells_supported: 977,
      graph_nodes: 1043,
      graph_edges: 6265,
    },
    warnings: [],
    error: null,
    ...overrides,
  };
}

function runResponse(
  overrides: Partial<CalculationRunResponse> = {},
): CalculationRunResponse {
  return {
    calculation_run_id: 'baseline-run',
    model_version_id: 'model-version',
    graph_version_id: 'graph-version',
    base_run_id: null,
    status: 'completed_with_warning',
    versions: {
      phase2_ir: '2',
      compiler: '3',
      engine: '4',
      registry: '5',
      semantics: '6',
    },
    summary: {
      formula_cells_total: 1043,
      formula_cells_supported: 977,
      unsupported_formula_cells: 12,
      calculated_formula_cells: 900,
      reused_formula_cells: 0,
      dirty_formula_cells: 1043,
      cycle_formula_cells: 0,
      blocked_formula_cells: 5,
      execution_error_cells: 0,
      grouped_calculation_rules: 20,
      graph_nodes: 1043,
      graph_edges: 6265,
    },
    warnings: [],
    values: [],
    ...overrides,
  };
}

test('workbook validation accepts only xlsx files up to the backend default limit', () => {
  assert.equal(
    validateWorkbookFile({
      name: 'Investment Model.XLSX',
      size: 25 * 1024 * 1024,
    }),
    null,
  );
  assert.deepEqual(
    validateWorkbookFile({ name: 'legacy.xls', size: 1024 }),
    {
      code: 'UNSUPPORTED_WORKBOOK_FORMAT',
      message: 'Choose an .xlsx workbook.',
    },
  );
  assert.deepEqual(
    validateWorkbookFile({
      name: 'oversized.xlsx',
      size: 25 * 1024 * 1024 + 1,
    }),
    {
      code: 'WORKBOOK_TOO_LARGE',
      message: 'Choose an .xlsx workbook no larger than 25 MB.',
    },
  );
});

test('supported percentage is stable for normal and zero-formula summaries', () => {
  assert.equal(formatSupportedPercentage(977, 1043), '93.7%');
  assert.equal(formatSupportedPercentage(0, 0), '—');
});

test('notifications deduplicate by source and code and use real run counts', () => {
  const notifications = buildPreparationNotifications({
    uploadResult: uploadResponse({
      warnings: [
        {
          code: 'CALCULATION_PREPARATION_FAILED',
          message: 'Calculation preparation failed.',
        },
      ],
    }),
    readiness: readinessResponse({
      warnings: [
        'unsupported_formula_cells',
        'blocked_by_dependency',
        'canonical_lineage_incomplete',
      ],
    }),
    activeRun: runResponse({
      warnings: ['unsupported_formula_cells', 'blocked_by_dependency'],
    }),
    error: null,
    stateNotice: null,
  });

  assert.deepEqual(
    notifications.map(({ severity, source, code, count }) => ({
      severity,
      source,
      code,
      count,
    })),
    [
      {
        severity: 'warning',
        source: 'upload',
        code: 'CALCULATION_PREPARATION_FAILED',
        count: null,
      },
      {
        severity: 'warning',
        source: 'readiness',
        code: 'unsupported_formula_cells',
        count: 12,
      },
      {
        severity: 'warning',
        source: 'readiness',
        code: 'blocked_by_dependency',
        count: 5,
      },
      {
        severity: 'warning',
        source: 'readiness',
        code: 'canonical_lineage_incomplete',
        count: null,
      },
      {
        severity: 'warning',
        source: 'calculation',
        code: 'unsupported_formula_cells',
        count: 12,
      },
      {
        severity: 'warning',
        source: 'calculation',
        code: 'blocked_by_dependency',
        count: 5,
      },
    ],
  );
});

test('blocking structured errors retain retry and resource details', () => {
  const error = new CalculationApiError(504, {
    code: 'UPLOAD_PROXY_TIMEOUT',
    message:
      'Model analysis exceeded the 30-minute proxy window and may still be running. Do not retry immediately.',
    retryable: false,
    resource_id: 'model-version',
  });

  const notifications = buildPreparationNotifications({
    uploadResult: null,
    readiness: null,
    activeRun: null,
    error,
    stateNotice: null,
  });

  assert.deepEqual(notifications, [
    {
      id: 'error:UPLOAD_PROXY_TIMEOUT',
      severity: 'error',
      source: 'request',
      code: 'UPLOAD_PROXY_TIMEOUT',
      message:
        'Model analysis exceeded the 30-minute proxy window and may still be running. Do not retry immediately.',
      count: null,
      retryable: false,
      resourceId: 'model-version',
    },
  ]);
});

test('technical details keep all identities and versions in one disclosure model', () => {
  const details = buildTechnicalDetails({
    uploadResult: uploadResponse({ runtime_seconds: 12.34567 }),
    readiness: readinessResponse(),
    baselineRun: runResponse(),
    overrideRun: runResponse({
      calculation_run_id: 'override-run',
      base_run_id: 'baseline-run',
    }),
  });

  assert.deepEqual(details.slice(0, 7), [
    { label: 'Filename', value: 'model.xlsx' },
    { label: 'Endpoint mode', value: 'workbook_agent' },
    { label: 'Runtime', value: '12.35 seconds' },
    { label: 'Model version', value: 'model-version' },
    { label: 'Workbook version', value: 'workbook-version' },
    { label: 'Graph version', value: 'graph-version' },
    { label: 'Extraction ID', value: 'extraction-id' },
  ]);
  assert.ok(
    details.some(
      ({ label, value }) =>
        label === 'Baseline run' && value === 'baseline-run',
    ),
  );
  assert.ok(
    details.some(
      ({ label, value }) =>
        label === 'Override run' && value === 'override-run',
    ),
  );
  assert.ok(
    details.some(
      ({ label, value }) =>
        label === 'Active run' && value === 'override-run',
    ),
  );
});
