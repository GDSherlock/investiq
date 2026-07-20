import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getCalculationInputs,
  getCalculationReadiness,
  getCalculationRun,
  prepareCalculation,
  runCalculation,
} from './api';
import type {
  CalculationApiError,
  CalculationRunResponse,
  WorkbookValidationResponse,
} from './calculation-api-types';
import {
  buildBaselineRequest,
  buildParameterOverrideRequest,
  canStartCalculationFlow,
  isCalculationReady,
  parseCalculationApiErrorPayload,
} from './calculation-flow';
import {
  CALCULATION_STORAGE_KEYS,
  clearCalculationArtifacts,
  persistUploadIdentity,
  readPersistedCalculationState,
  reconcileStoredRun,
  shouldAutoRunBaseline,
  type StorageLike,
} from './calculation-storage';
import {
  diffCalculationRunValues,
  typedValuesEqual,
} from './calculation-value-utils';

class MemoryStorage implements StorageLike {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

function uploadResponse(
  overrides: Partial<WorkbookValidationResponse> = {},
): WorkbookValidationResponse {
  return {
    workbook_version_id: 'workbook-version',
    model_version_id: 'model-version',
    endpoint_mode: 'workbook_agent',
    filename: 'model.xlsx',
    runtime_seconds: 1,
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

function runResponse(
  overrides: Partial<CalculationRunResponse> = {},
): CalculationRunResponse {
  return {
    calculation_run_id: 'run-id',
    model_version_id: 'model-version',
    graph_version_id: 'graph-version',
    base_run_id: null,
    status: 'completed',
    versions: {
      phase2_ir: '1',
      compiler: '1',
      engine: '1',
      registry: '1',
      semantics: '1',
    },
    summary: {
      formula_cells_total: 1,
      formula_cells_supported: 1,
      unsupported_formula_cells: 0,
      calculated_formula_cells: 1,
      reused_formula_cells: 0,
      dirty_formula_cells: 1,
      cycle_formula_cells: 0,
      blocked_formula_cells: 0,
      execution_error_cells: 0,
      grouped_calculation_rules: 1,
      graph_nodes: 1,
      graph_edges: 0,
    },
    warnings: [],
    values: [],
    ...overrides,
  };
}

test('structured API errors preserve backend detail fields', () => {
  const error = parseCalculationApiErrorPayload(409, 'Conflict', {
    detail: {
      code: 'GRAPH_VERSION_MISMATCH',
      message: 'Graph does not match the model.',
      retryable: false,
      resource_id: 'graph-version',
    },
  });

  assert.equal(error.status, 409);
  assert.equal(error.code, 'GRAPH_VERSION_MISMATCH');
  assert.equal(error.message, 'Graph does not match the model.');
  assert.equal(error.retryable, false);
  assert.equal(error.resourceId, 'graph-version');
});

test('submitted=false never opens the calculation flow', () => {
  assert.equal(
    canStartCalculationFlow(
      uploadResponse({
        submitted: false,
        stop_reason: 'deadline_exceeded',
      }),
    ),
    false,
  );
  assert.equal(
    canStartCalculationFlow(
      uploadResponse({
        workbook_version_id: null,
      }),
    ),
    false,
  );
});

test('ready_with_warning remains calculable', () => {
  assert.equal(isCalculationReady('ready'), true);
  assert.equal(isCalculationReady('ready_with_warning'), true);
  assert.equal(isCalculationReady('failed'), false);
});

test('new uploads clear only calculation graph and run state', () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.workbookVersionId, 'old-workbook');
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'old-model');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'old-graph');
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'old-baseline');
  storage.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'old-override');
  storage.setItem('investiq_model_id', 'legacy-model');

  clearCalculationArtifacts(storage);
  persistUploadIdentity(storage, uploadResponse());

  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.workbookVersionId),
    'workbook-version',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.modelVersionId),
    'model-version',
  );
  assert.equal(storage.getItem(CALCULATION_STORAGE_KEYS.graphVersionId), null);
  assert.equal(storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId), null);
  assert.equal(storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId), null);
  assert.equal(storage.getItem('investiq_model_id'), 'legacy-model');
});

test('baseline and canonical parameter requests preserve string numbers', () => {
  assert.deepEqual(buildBaselineRequest('graph-version'), {
    graph_version_id: 'graph-version',
    overrides: [],
    idempotency_key: null,
  });
  assert.deepEqual(
    buildParameterOverrideRequest('graph-version', 'parameter-uuid', ' 63 '),
    {
      graph_version_id: 'graph-version',
      overrides: [
        {
          target: {
            kind: 'parameter',
            parameter_id: 'parameter-uuid',
          },
          value: {
            value_type: 'number',
            value: '63',
          },
        },
      ],
      idempotency_key: null,
    },
  );
});

test('override requests reject empty, non-finite, and illegal numeric strings', () => {
  for (const value of ['', 'NaN', 'Infinity', '0x10', '12 units']) {
    assert.throws(
      () => buildParameterOverrideRequest('graph', 'parameter', value),
      /finite numeric string/i,
    );
  }
});

test('typed equality compares the full discriminated value', () => {
  assert.equal(
    typedValuesEqual(
      { value_type: 'number', value: '62' },
      { value_type: 'number', value: '62' },
    ),
    true,
  );
  assert.equal(
    typedValuesEqual(
      { value_type: 'number', value: '62' },
      { value_type: 'number', value: '62.0' },
    ),
    false,
  );
  assert.equal(
    typedValuesEqual(
      { value_type: 'date_serial', value: '45292', iso_evidence: '2024-01-01' },
      { value_type: 'date_serial', value: '45292', iso_evidence: null },
    ),
    false,
  );
  assert.equal(
    typedValuesEqual(
      { value_type: 'error', error_code: '#DIV/0!' },
      { value_type: 'text', value: '#DIV/0!' },
    ),
    false,
  );
});

test('changed-value diff is indexed by formula_cell_id and no-change is empty', () => {
  const baseline = runResponse({
    values: [
      {
        formula_cell_id: 'formula-a',
        sheet_name: 'Model',
        cell_address: 'B2',
        status: 'calculated',
        value: { value_type: 'number', value: '100' },
        engine_error_code: null,
        reused_from_run_id: null,
        validation_status: 'validated',
        warnings: [],
      },
      {
        formula_cell_id: 'formula-b',
        sheet_name: 'Model',
        cell_address: 'B3',
        status: 'calculated',
        value: { value_type: 'boolean', value: true },
        engine_error_code: null,
        reused_from_run_id: null,
        validation_status: 'validated',
        warnings: [],
      },
    ],
  });
  const override = runResponse({
    values: baseline.values.map((value) =>
      value.formula_cell_id === 'formula-a'
        ? {
            ...value,
            value: { value_type: 'number' as const, value: '101' },
            warnings: ['changed'],
          }
        : value,
    ),
  });

  const changed = diffCalculationRunValues(baseline.values, override.values);
  assert.equal(changed.length, 1);
  assert.equal(changed[0].formulaCellId, 'formula-a');
  assert.equal(changed[0].override.warnings[0], 'changed');
  assert.deepEqual(
    diffCalculationRunValues(override.values, override.values),
    [],
  );
});

test('persisted run reload suppresses automatic recalculation', () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.workbookVersionId, 'workbook-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'graph-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'baseline-run');
  storage.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'override-run');

  const persisted = readPersistedCalculationState(storage);
  assert.equal(shouldAutoRunBaseline(persisted), false);
  assert.equal(persisted.baselineRunId, 'baseline-run');
  assert.equal(persisted.overrideRunId, 'override-run');
});

test('stale run IDs are cleared without mixing model or graph values', () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'stale-run');

  const result = reconcileStoredRun(
    storage,
    'baseline',
    runResponse({ model_version_id: 'different-model' }),
    'model-version',
    'graph-version',
  );

  assert.equal(result.isCurrent, false);
  assert.equal(result.notice?.includes('different model or graph'), true);
  assert.equal(storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId), null);
});

test('calculation API methods use the versioned proxy contract', async () => {
  const originalFetch = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (
    input: string | URL | Request,
    init?: RequestInit,
  ) => {
    calls.push({ url: String(input), init });
    if (String(input).includes('/inputs')) {
      return new Response(
        JSON.stringify({
          model_version_id: 'model-version',
          graph_version_id: 'graph-version',
          inputs: [],
          next_cursor: null,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }
    if (String(input).includes('/calculations')) {
      return new Response(JSON.stringify(runResponse()), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (String(input).includes('/calculation-runs/')) {
      return new Response(JSON.stringify(runResponse()), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response(
      JSON.stringify({
        model_version_id: 'model-version',
        workbook_version_id: 'workbook-version',
        model_status: 'materialized',
        validation_status: 'validated',
        status: 'not_prepared',
        calculation_rule_extraction_id: null,
        graph_version_id: null,
        versions: {
          phase1_ir: '1',
          phase2_ir: '1',
          compiler: '1',
          engine: '1',
          registry: '1',
          semantics: '1',
        },
        summary: {
          formula_cells_total: 0,
          formula_cells_supported: 0,
          graph_nodes: 0,
          graph_edges: 0,
        },
        warnings: [],
        error: null,
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    );
  }) as typeof fetch;

  try {
    await getCalculationReadiness('model-version');
    await prepareCalculation('model-version');
    await getCalculationInputs('model-version', {
      targetKind: 'parameter',
      editableOnly: true,
      limit: 100,
      cursor: 'cursor-id',
    });
    await runCalculation('model-version', buildBaselineRequest('graph-version'));
    await getCalculationRun('run-id');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    '/api/v1/models/model-version/calculation/readiness',
  );
  assert.equal(calls[1].init?.method, 'POST');
  assert.equal(
    calls[2].url,
    '/api/v1/models/model-version/calculation/inputs?target_kind=parameter&editable_only=true&limit=100&cursor=cursor-id',
  );
  assert.deepEqual(JSON.parse(String(calls[3].init?.body)), {
    graph_version_id: 'graph-version',
    overrides: [],
    idempotency_key: null,
  });
  assert.equal(calls[4].url, '/api/v1/calculation-runs/run-id');
});

test('calculation API methods throw structured backend errors', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        detail: {
          code: 'MODEL_NOT_MATERIALIZED',
          message: 'Model is not ready.',
          retryable: true,
          resource_id: 'model-version',
        },
      }),
      {
        status: 409,
        statusText: 'Conflict',
        headers: { 'Content-Type': 'application/json' },
      },
    )) as typeof fetch;

  try {
    await assert.rejects(
      () => prepareCalculation('model-version'),
      (error: CalculationApiError) =>
        error.code === 'MODEL_NOT_MATERIALIZED' &&
        error.retryable === true &&
        error.resourceId === 'model-version',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
