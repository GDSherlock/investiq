import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  getCalculationInputs,
  getCalculationReadiness,
  getCalculationRun,
  getCalculationRunOutputs,
  getModel,
  prepareCalculation,
  runCalculation,
  runCalculationSensitivity,
} from './api';
import type {
  CalculationApiError,
  CalculationSensitivityRequest,
  CalculationSensitivityResponse,
  CalculationRunOutputsResponse,
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
  SENSITIVITY_WORKBENCH_VERSION,
  clearCalculationArtifacts,
  persistGraphVersionId,
  persistSensitivityRunSelection,
  persistSensitivityWorkbenchDocument,
  persistUploadIdentity,
  readPersistedCalculationState,
  readSensitivityWorkbenchDocument,
  reconcileStoredRun,
  shouldAutoRunBaseline,
  type StorageLike,
} from './calculation-storage';
import {
  diffCalculationRunValues,
  typedValuesEqual,
} from './calculation-value-utils';
import {
  buildSensitivityOutputView,
  selectSensitivityRunId,
} from './sensitivity-output-adapter';
import {
  buildSensitivityRequest,
  buildTornadoRows,
  buildTwoWayMatrix,
  canApplySensitivityResponse,
  deriveSliderSpec,
  loadAllEditableNumericParameters,
  restoreSensitivityOutputProjection,
  selectDefaultSensitivityOutput,
  type SensitivityAssumption,
} from './sensitivity-analysis';

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

function runOutputsResponse(
  overrides: Partial<CalculationRunOutputsResponse> = {},
): CalculationRunOutputsResponse {
  return {
    calculation_run_id: 'override-run',
    model_version_id: 'model-version',
    graph_version_id: 'graph-version',
    base_run_id: 'baseline-run',
    comparison_baseline_run_id: 'baseline-run',
    outputs: [],
    ...overrides,
  };
}

function projectedNumber(value: string) {
  return {
    availability_status: 'available' as const,
    value: { value_type: 'number' as const, value },
    unavailable_reason: null,
    execution_status: 'executed',
    engine_error_code: null,
    validation_status: 'validated',
    warnings: [],
  };
}

function unavailableProjection(reason = 'unsupported') {
  return {
    availability_status: 'unavailable' as const,
    value: null,
    unavailable_reason: reason,
    execution_status: reason,
    engine_error_code: null,
    validation_status: 'not_validated',
    warnings: [],
  };
}

function sensitivityResponse(
  overrides: Partial<CalculationSensitivityResponse> = {},
): CalculationSensitivityResponse {
  return {
    model_version_id: 'model-version',
    graph_version_id: 'graph-version',
    comparison_baseline_run_id: 'baseline-run',
    current_run_id: 'override-run',
    selected_output: {
      output_id: 'project-irr-output',
      business_role: 'project_irr',
      label: 'Project IRR',
      unit: '%',
      scenario: null,
      number_format: '0.0%',
      mapping_status: 'mapped',
      support_status: 'supported',
      availability_status: 'available',
      baseline: projectedNumber('0.1'),
      current: projectedNumber('0.12'),
    },
    drivers: [],
    two_way: null,
    warnings: [],
    ...overrides,
  };
}

function numericAssumption(
  targetId: string,
  currentValue: string,
  overrides: Partial<SensitivityAssumption> = {},
): SensitivityAssumption {
  return {
    targetKey: `parameter:${targetId}`,
    target: { kind: 'parameter', parameter_id: targetId },
    label: targetId,
    category: null,
    unit: null,
    scenario: null,
    period: null,
    currentValue,
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

test('does not call legacy model API without a legacy model id', async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = (async () => {
    fetchCalls += 1;
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;

  try {
    for (const modelId of [undefined, null, '', ' ', 'undefined', 'null']) {
      await assert.rejects(
        () => getModel(modelId as unknown as string),
        /valid legacy model id/i,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(fetchCalls, 0);
});

test('restores calculation flow from model version storage', async () => {
  const storage = new MemoryStorage();
  storage.setItem(
    CALCULATION_STORAGE_KEYS.modelVersionId,
    'stored-model-version',
  );
  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'stored-workbook-version',
  );
  const persisted = readPersistedCalculationState(storage);
  const pageSource = readFileSync('src/app/page.tsx', 'utf8');
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request) => {
    calls.push(String(input));
    return new Response(
      JSON.stringify({
        model_version_id: 'stored-model-version',
        workbook_version_id: 'stored-workbook-version',
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
    assert.equal(persisted.modelVersionId, 'stored-model-version');
    assert.equal(persisted.workbookVersionId, 'stored-workbook-version');
    await getCalculationReadiness(persisted.modelVersionId);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(calls, [
    '/api/v1/models/stored-model-version/calculation/readiness',
  ]);
  assert.match(pageSource, /readRestorableCalculationIdentity/);
  assert.match(pageSource, /source:\s*'storage'/);
});

test('introduction Skip does not lose restore state', () => {
  const storage = new MemoryStorage();
  storage.setItem(
    CALCULATION_STORAGE_KEYS.modelVersionId,
    'stored-model-version',
  );
  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'stored-workbook-version',
  );
  const authGuardSource = readFileSync('src/app/AuthGuard.tsx', 'utf8');
  const beforeSkip = readPersistedCalculationState(storage);
  let restoreCalls = 0;

  if (beforeSkip.modelVersionId && beforeSkip.workbookVersionId) {
    restoreCalls += 1;
  }
  const afterSkip = readPersistedCalculationState(storage);

  assert.equal(afterSkip.modelVersionId, 'stored-model-version');
  assert.equal(afterSkip.workbookVersionId, 'stored-workbook-version');
  assert.equal(restoreCalls, 1);
  assert.match(
    authGuardSource,
    /return\s*\(\s*<>\s*\{children\}\s*\{showIntro[\s\S]*<IntroductionPage/,
  );
});

test('no repeated failing requests without a usable legacy id', () => {
  const navBarSource = readFileSync('src/app/NavBar.tsx', 'utf8');

  assert.match(navBarSource, /loadLegacyModelIfAvailable/);
  assert.doesNotMatch(
    navBarSource,
    /fetch\(`\/api\/v1\/models\/\$\{id\}`/,
  );
  assert.match(navBarSource, /isUsableLegacyModelId/);
});

test('existing run reload uses GET without recalculating', async () => {
  const originalFetch = globalThis.fetch;
  const calls: { url: string; method: string }[] = [];
  const panelSource = readFileSync(
    'src/components/calculation/CalculationPreparationPanel.tsx',
    'utf8',
  );
  globalThis.fetch = (async (
    input: string | URL | Request,
    init?: RequestInit,
  ) => {
    calls.push({
      url: String(input),
      method: init?.method ?? 'GET',
    });
    return new Response(JSON.stringify(runResponse()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;

  try {
    await getCalculationRun('baseline-run');
    await getCalculationRun('override-run');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(calls, [
    { url: '/api/v1/calculation-runs/baseline-run', method: 'GET' },
    { url: '/api/v1/calculation-runs/override-run', method: 'GET' },
  ]);
  assert.match(panelSource, /restoreFromStorage/);
  assert.match(
    panelSource,
    /restoreFromStorage[\s\S]*No calculation was submitted/,
  );
});

test('successful override shows an inline receipt before the returned inputs table', () => {
  const preparationPanelSource = readFileSync(
    'src/components/calculation/CalculationPreparationPanel.tsx',
    'utf8',
  );
  const inputPanelSource = readFileSync(
    'src/components/calculation/CalculationInputPanel.tsx',
    'utf8',
  );

  assert.match(preparationPanelSource, /setLastOverrideReceipt\(\{/);
  assert.match(inputPanelSource, /Override submitted/);
  assert.match(inputPanelSource, /Model input value before override/);
  assert.match(inputPanelSource, /persisted formula values changed/);
  assert.ok(
    inputPanelSource.indexOf('Override submitted') <
      inputPanelSource.indexOf('<details'),
    'the override receipt should stay visible above the expandable input table',
  );
});

test('sensitivity adapter maps scalar KPIs by canonical role with real before and after values', () => {
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'project-irr-output',
          entity_kind: 'scalar',
          business_role: 'project_irr',
          label: 'Unlevered return',
          unit: '%',
          scenario: null,
          formula_cell_id: 'formula-project-irr',
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0%',
          availability_status: 'available',
          baseline: projectedNumber('0.1'),
          current: projectedNumber('0.12'),
        },
      ],
    }),
  );

  assert.equal(view.kpis.length, 1);
  assert.deepEqual(
    {
      outputId: view.kpis[0].outputId,
      role: view.kpis[0].businessRole,
      baseline: view.kpis[0].baseline.numericValue,
      current: view.kpis[0].current.numericValue,
      absoluteChange: view.kpis[0].absoluteChange,
      percentageChange: view.kpis[0].percentageChange,
    },
    {
      outputId: 'project-irr-output',
      role: 'project_irr',
      baseline: 0.1,
      current: 0.12,
      absoluteChange: 0.01999999999999999,
      percentageChange: 19.99999999999999,
    },
  );
  assert.doesNotMatch(JSON.stringify(view), /formula-project-irr|sheet_name|cell_address/);
});

test('unsupported outputs stay unavailable and missing KPI roles are not fabricated', () => {
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'equity-irr-output',
          entity_kind: 'scalar',
          business_role: 'equity_irr',
          label: 'Equity return',
          unit: '%',
          scenario: null,
          formula_cell_id: 'formula-equity-irr',
          mapping_status: 'mapped',
          support_status: 'unsupported',
          number_format: '0.0%',
          availability_status: 'unavailable',
          baseline: unavailableProjection('unsupported'),
          current: unavailableProjection('unsupported'),
        },
      ],
    }),
  );

  assert.deepEqual(view.kpis.map((kpi) => kpi.businessRole), ['equity_irr']);
  assert.equal(view.kpis[0].availabilityStatus, 'unavailable');
  assert.equal(view.kpis[0].current.numericValue, null);
  assert.equal(view.kpis[0].current.unavailableReason, 'unsupported');
  assert.equal(view.kpis.some((kpi) => kpi.businessRole === 'npv'), false);
});

test('sensitivity adapter orders canonical series points and compares each stable value ID', () => {
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'revenue-output',
          entity_kind: 'series',
          business_role: 'revenue',
          label: 'Revenue',
          unit: 'USD M',
          scenario: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          availability_status: 'partial',
          points: [
            {
              financial_series_value_id: 'revenue-2029',
              period_index: 2,
              period: '2029',
              formula_cell_id: 'formula-revenue-2029',
              mapping_status: 'mapped',
              support_status: 'supported',
              number_format: '0.0',
              availability_status: 'unavailable',
              baseline: projectedNumber('120'),
              current: unavailableProjection('blocked'),
            },
            {
              financial_series_value_id: 'revenue-2027',
              period_index: 0,
              period: '2027',
              formula_cell_id: 'formula-revenue-2027',
              mapping_status: 'mapped',
              support_status: 'supported',
              number_format: '0.0',
              availability_status: 'available',
              baseline: projectedNumber('100'),
              current: projectedNumber('105'),
            },
            {
              financial_series_value_id: 'revenue-2028',
              period_index: 1,
              period: '2028',
              formula_cell_id: 'formula-revenue-2028',
              mapping_status: 'mapped',
              support_status: 'supported',
              number_format: '0.0',
              availability_status: 'available',
              baseline: projectedNumber('110'),
              current: projectedNumber('110'),
            },
          ],
        },
      ],
    }),
  );

  assert.equal(view.series.length, 1);
  assert.deepEqual(
    view.series[0].points.map((point) => ({
      id: point.financialSeriesValueId,
      period: point.period,
      baseline: point.baseline.numericValue,
      current: point.current.numericValue,
    })),
    [
      {
        id: 'revenue-2027',
        period: '2027',
        baseline: 100,
        current: 105,
      },
      {
        id: 'revenue-2028',
        period: '2028',
        baseline: 110,
        current: 110,
      },
      {
        id: 'revenue-2029',
        period: '2029',
        baseline: 120,
        current: null,
      },
    ],
  );
  assert.equal(view.series[0].changedPointCount, 1);
  assert.equal(view.series[0].maxAbsoluteChange, 5);
  assert.equal(view.series[0].unavailableCurrentPointCount, 1);
  assert.deepEqual(view.series[0].unavailableCurrentReasons, ['blocked']);
  assert.doesNotMatch(
    JSON.stringify(view.series[0]),
    /formula-revenue|sheet_name|cell_address/,
  );
});

test('sensitivity reload selects override first and otherwise falls back to baseline', () => {
  const state = {
    workbookVersionId: 'workbook-version',
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    baselineRunId: 'baseline-run',
    overrideRunId: 'override-run',
  };

  assert.equal(selectSensitivityRunId(state), 'override-run');
  assert.equal(
    selectSensitivityRunId({ ...state, overrideRunId: null }),
    'baseline-run',
  );
  assert.equal(
    selectSensitivityRunId({
      ...state,
      overrideRunId: null,
      baselineRunId: null,
    }),
    null,
  );
});

test('run output projection API uses GET and the business-output route', async () => {
  const originalFetch = globalThis.fetch;
  const calls: { url: string; method: string }[] = [];
  globalThis.fetch = (async (
    input: string | URL | Request,
    init?: RequestInit,
  ) => {
    calls.push({
      url: String(input),
      method: init?.method ?? 'GET',
    });
    return new Response(JSON.stringify(runOutputsResponse()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;

  try {
    const response = await getCalculationRunOutputs('override-run');
    assert.equal(response.calculation_run_id, 'override-run');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(calls, [
    {
      url: '/api/v1/calculation-runs/override-run/outputs',
      method: 'GET',
    },
  ]);
});

test('formal Sensitivity page consumes projected outputs without legacy KPI interpolation', () => {
  const pageSource = readFileSync('src/app/sensitivity/page.tsx', 'utf8');

  assert.match(pageSource, /getCalculationRunOutputs/);
  assert.match(pageSource, /readPersistedCalculationState/);
  assert.match(pageSource, /buildSensitivityOutputView/);
  assert.doesNotMatch(pageSource, /\bgetModel\b/);
  assert.doesNotMatch(pageSource, /parsed_json/);
  assert.doesNotMatch(pageSource, /\binterp\s*\(/);
  assert.doesNotMatch(pageSource, /baseIrr\s*=\s*0\.123/);
  assert.doesNotMatch(pageSource, /piecewise-linear interpolation/);
  assert.doesNotMatch(pageSource, /sheet_name|cell_address/);
});

test('canonical sensitivity API posts the exact request body to the model route', async () => {
  const request: CalculationSensitivityRequest = {
    graph_version_id: 'graph-version',
    output_id: 'project-irr-output',
    current_overrides: [],
    drivers: [
      {
        target: { kind: 'parameter', parameter_id: 'driver-id' },
        low: { value_type: 'number', value: '80' },
        high: { value_type: 'number', value: '120' },
      },
    ],
    two_way: null,
  };
  const originalFetch = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (
    input: string | URL | Request,
    init?: RequestInit,
  ) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify(sensitivityResponse()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;

  try {
    const response = await runCalculationSensitivity('model/version', request);
    assert.equal(response.current_run_id, 'override-run');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url,
    '/api/v1/models/model%2Fversion/calculation/sensitivity',
  );
  assert.equal(calls[0].init?.method, 'POST');
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), request);
});

test('editable numeric parameter loading follows every cursor and returns stable canonical assumptions', async () => {
  const cursors: Array<string | undefined> = [];
  const getInputs: typeof getCalculationInputs = async (
    modelVersionId,
    options = {},
  ) => {
    assert.equal(modelVersionId, 'model-version');
    assert.equal(options.targetKind, 'parameter');
    assert.equal(options.editableOnly, true);
    cursors.push(options.cursor);
    if (options.cursor === undefined) {
      return {
        model_version_id: modelVersionId,
        graph_version_id: 'graph-version',
        inputs: [
          {
            target_kind: 'parameter',
            target_id: 'b-id',
            label: 'Beta',
            category: 'Costs',
            unit: 'USD',
            scenario: null,
            period: null,
            current_value: { value_type: 'number', value: '2' },
            editable: true,
            non_editable_reason: null,
          },
          {
            target_kind: 'parameter',
            target_id: 'ignored-text',
            label: 'Text',
            category: 'Costs',
            unit: null,
            scenario: null,
            period: null,
            current_value: { value_type: 'text', value: 'n/a' },
            editable: true,
            non_editable_reason: null,
          },
        ],
        next_cursor: 'next-page',
      };
    }
    return {
      model_version_id: modelVersionId,
      graph_version_id: 'graph-version',
      inputs: [
        {
          target_kind: 'parameter',
          target_id: 'a-id',
          label: 'Alpha',
          category: 'Costs',
          unit: null,
          scenario: 'Base',
          period: null,
          current_value: { value_type: 'number', value: '1.25' },
          editable: true,
          non_editable_reason: null,
        },
        {
          target_kind: 'parameter',
          target_id: 'ignored-locked',
          label: 'Locked',
          category: 'Costs',
          unit: null,
          scenario: null,
          period: null,
          current_value: { value_type: 'number', value: '9' },
          editable: false,
          non_editable_reason: 'derived',
        },
      ],
      next_cursor: null,
    };
  };

  const assumptions = await loadAllEditableNumericParameters(
    'model-version',
    getInputs,
  );

  assert.deepEqual(cursors, [undefined, 'next-page']);
  assert.deepEqual(
    assumptions.map((assumption) => ({
      targetKey: assumption.targetKey,
      label: assumption.label,
      category: assumption.category,
      value: assumption.currentValue,
    })),
    [
      {
        targetKey: 'parameter:a-id',
        label: 'Alpha',
        category: 'Costs',
        value: '1.25',
      },
      {
        targetKey: 'parameter:b-id',
        label: 'Beta',
        category: 'Costs',
        value: '2',
      },
    ],
  );
  assert.doesNotMatch(
    JSON.stringify(assumptions),
    /sheet_name|cell_address|formula_cell_id/,
  );
});

test('slider ranges use absolute twenty-percent bounds and one-hundred steps', () => {
  assert.deepEqual(deriveSliderSpec('100'), {
    kind: 'range',
    min: '80',
    max: '120',
    step: '0.4',
  });
  assert.deepEqual(deriveSliderSpec('-50'), {
    kind: 'range',
    min: '-60',
    max: '-40',
    step: '0.2',
  });
  assert.deepEqual(deriveSliderSpec('0.1'), {
    kind: 'range',
    min: '0.08',
    max: '0.12',
    step: '0.0004',
  });
  assert.deepEqual(deriveSliderSpec('0'), { kind: 'number' });
});

test('default output prioritizes available project IRR, equity IRR, NPV, then display order', () => {
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'other-output',
          entity_kind: 'scalar',
          business_role: 'other',
          label: 'A metric',
          unit: null,
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: null,
          availability_status: 'available',
          baseline: projectedNumber('1'),
          current: projectedNumber('2'),
        },
        {
          output_id: 'npv-output',
          entity_kind: 'scalar',
          business_role: 'npv',
          label: 'NPV',
          unit: null,
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: null,
          availability_status: 'available',
          baseline: projectedNumber('3'),
          current: projectedNumber('4'),
        },
        {
          output_id: 'project-irr-output',
          entity_kind: 'scalar',
          business_role: 'project_irr',
          label: 'Project IRR',
          unit: null,
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'unsupported',
          number_format: null,
          availability_status: 'unavailable',
          baseline: unavailableProjection(),
          current: unavailableProjection(),
        },
      ],
    }),
  );

  assert.equal(selectDefaultSensitivityOutput(view.kpis), 'npv-output');
  assert.equal(
    selectDefaultSensitivityOutput(
      view.kpis.filter((kpi) => kpi.businessRole === 'other'),
    ),
    'other-output',
  );
  assert.equal(selectDefaultSensitivityOutput([]), null);
});

test('sensitivity request uses canonical targets, changed overrides, driver cap, and exact actual axes', () => {
  const assumptions = Array.from({ length: 13 }, (_, index) =>
    numericAssumption(`driver-${index + 1}`, index === 0 ? '0.1' : '100', {
      label: `Driver ${index + 1}`,
    }),
  );
  const request = buildSensitivityRequest({
    graphVersionId: 'graph-version',
    outputId: 'project-irr-output',
    assumptions,
    overridesByTarget: {
      'parameter:driver-1': '0.2',
      'parameter:driver-13': '125',
      'cell:Inputs!A1': '999',
    },
    tornadoDriverKeys: assumptions.map((assumption) => assumption.targetKey),
    rowDriverKey: 'parameter:driver-1',
    columnDriverKey: 'parameter:driver-2',
  });

  assert.equal(request.drivers.length, 12);
  assert.deepEqual(request.current_overrides, [
    {
      target: { kind: 'parameter', parameter_id: 'driver-1' },
      value: { value_type: 'number', value: '0.2' },
    },
    {
      target: { kind: 'parameter', parameter_id: 'driver-13' },
      value: { value_type: 'number', value: '125' },
    },
  ]);
  assert.deepEqual(
    request.two_way?.row.values.map((value) => value.value),
    ['0.16', '0.18', '0.2', '0.22', '0.24'],
  );
  assert.deepEqual(
    request.two_way?.column.values.map((value) => value.value),
    ['80', '90', '100', '110', '120'],
  );
  assert.doesNotMatch(JSON.stringify(request), /sheet_name|cell_address|cell:/);
});

test('two-way request is omitted for missing, equal, or zero-valued axes', () => {
  const assumptions = [
    numericAssumption('zero', '0'),
    numericAssumption('one', '1'),
  ];
  const common = {
    graphVersionId: 'graph-version',
    outputId: 'output-id',
    assumptions,
    overridesByTarget: {},
    tornadoDriverKeys: ['parameter:one'],
  };

  assert.equal(
    buildSensitivityRequest({
      ...common,
      rowDriverKey: null,
      columnDriverKey: 'parameter:one',
    }).two_way,
    null,
  );
  assert.equal(
    buildSensitivityRequest({
      ...common,
      rowDriverKey: 'parameter:one',
      columnDriverKey: 'parameter:one',
    }).two_way,
    null,
  );
  assert.equal(
    buildSensitivityRequest({
      ...common,
      rowDriverKey: 'parameter:zero',
      columnDriverKey: 'parameter:one',
    }).two_way,
    null,
  );
});

test('versioned sensitivity workbench round-trips only for the matching model and graph', () => {
  const storage = new MemoryStorage();
  const driverKey =
    'parameter:11111111-1111-4111-8111-111111111111';
  const document = {
    version: SENSITIVITY_WORKBENCH_VERSION,
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    overridesByTarget: { [driverKey]: '12.5' },
    tornadoDriverKeys: [driverKey],
    selectedOutputId: 'output-id',
    rowDriverKey: driverKey,
    columnDriverKey: null,
  };

  persistSensitivityWorkbenchDocument(storage, document);
  assert.deepEqual(
    readSensitivityWorkbenchDocument(
      storage,
      'model-version',
      'graph-version',
    ),
    document,
  );
  assert.equal(
    readSensitivityWorkbenchDocument(
      storage,
      'other-model',
      'graph-version',
    ),
    null,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});

test('corrupt workbench state is cleared and storage failures do not escape', () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench, '{bad json');
  assert.equal(
    readSensitivityWorkbenchDocument(
      storage,
      'model-version',
      'graph-version',
    ),
    null,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );

  const throwingStorage: StorageLike = {
    getItem() {
      throw new Error('blocked');
    },
    removeItem() {
      throw new Error('blocked');
    },
    setItem() {
      throw new Error('blocked');
    },
  };
  assert.doesNotThrow(() => clearCalculationArtifacts(throwingStorage));
  assert.equal(
    readSensitivityWorkbenchDocument(
      throwingStorage,
      'model-version',
      'graph-version',
    ),
    null,
  );
});

test('artifact clearing and graph changes remove the sensitivity workbench document', () => {
  const storage = new MemoryStorage();
  const storeDocument = () =>
    storage.setItem(
      CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
      JSON.stringify({
        version: 1,
        modelVersionId: 'model-version',
        graphVersionId: 'old-graph',
        overridesByTarget: {},
        tornadoDriverKeys: [],
        selectedOutputId: null,
        rowDriverKey: null,
        columnDriverKey: null,
      }),
    );

  storeDocument();
  clearCalculationArtifacts(storage);
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );

  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'old-graph');
  storeDocument();
  persistGraphVersionId(storage, 'new-graph');
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});

test('sensitivity run selection uses only explicit comparison baseline and current IDs', () => {
  const storage = new MemoryStorage();
  persistSensitivityRunSelection(
    storage,
    sensitivityResponse({
      comparison_baseline_run_id: 'comparison-baseline',
      current_run_id: 'current-run',
    }),
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
    'comparison-baseline',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'current-run',
  );

  persistSensitivityRunSelection(
    storage,
    sensitivityResponse({
      comparison_baseline_run_id: 'comparison-baseline',
      current_run_id: 'comparison-baseline',
    }),
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    null,
  );
});

test('GET-only sensitivity restore clears a structured missing override then loads baseline', async () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'baseline-run');
  storage.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'missing-override');
  const calls: string[] = [];

  const result = await restoreSensitivityOutputProjection(
    storage,
    readPersistedCalculationState(storage),
    async (runId) => {
      calls.push(runId);
      if (runId === 'missing-override') {
        throw Object.assign(new Error('not found'), {
          status: 404,
          code: 'CALCULATION_RUN_NOT_FOUND',
          detail: {
            code: 'CALCULATION_RUN_NOT_FOUND',
            message: 'not found',
            retryable: false,
            resource_id: runId,
          },
        });
      }
      return runOutputsResponse({ calculation_run_id: runId });
    },
  );

  assert.deepEqual(calls, ['missing-override', 'baseline-run']);
  assert.equal(result?.calculation_run_id, 'baseline-run');
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    null,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
    'baseline-run',
  );
});

test('revision/model/graph/output guard rejects stale sensitivity responses', () => {
  const response = sensitivityResponse();
  const expected = {
    requestRevision: 2,
    currentRevision: 2,
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    outputId: 'project-irr-output',
  };
  assert.equal(canApplySensitivityResponse(response, expected), true);
  assert.equal(
    canApplySensitivityResponse(response, {
      ...expected,
      requestRevision: 1,
    }),
    false,
  );
  assert.equal(
    canApplySensitivityResponse(response, {
      ...expected,
      outputId: 'other-output',
    }),
    false,
  );
});

test('output adapter retains unclassified outputs and compares against the explicit baseline', () => {
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      calculation_run_id: 'baseline-run',
      base_run_id: 'unrelated-parent-run',
      comparison_baseline_run_id: 'baseline-run',
      outputs: [
        {
          output_id: 'unclassified-scalar',
          entity_kind: 'scalar',
          business_role: 'unclassified',
          label: 'Other scalar',
          unit: null,
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: null,
          availability_status: 'available',
          baseline: projectedNumber('1'),
          current: projectedNumber('1'),
        },
        {
          output_id: 'unclassified-series',
          entity_kind: 'series',
          business_role: 'unclassified',
          label: 'Other series',
          unit: null,
          scenario: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          availability_status: 'available',
          points: [],
        },
      ],
    }),
  );

  assert.deepEqual(view.kpis.map((item) => item.outputId), [
    'unclassified-scalar',
  ]);
  assert.deepEqual(view.series.map((item) => item.outputId), [
    'unclassified-series',
  ]);
  assert.equal(view.comparisonBaselineRunId, 'baseline-run');
  assert.equal(view.hasOverride, false);
});

test('tornado rows join canonical targets, rank absolute impact, and retain unavailable cases', () => {
  const assumptions = new Map([
    [
      'parameter:high-impact',
      numericAssumption('high-impact', '10', { label: 'High impact' }),
    ],
    [
      'parameter:unavailable',
      numericAssumption('unavailable', '5', { label: 'Unavailable driver' }),
    ],
  ]);
  const rows = buildTornadoRows(
    sensitivityResponse({
      selected_output: {
        ...sensitivityResponse().selected_output,
        current: projectedNumber('100'),
      },
      drivers: [
        {
          target: { kind: 'parameter', parameter_id: 'unavailable' },
          low_case: {
            input_value: { value_type: 'number', value: '4' },
            calculation_run_id: 'unavailable-low-run',
            output: unavailableProjection('blocked'),
            warnings: [],
          },
          high_case: {
            input_value: { value_type: 'number', value: '6' },
            calculation_run_id: 'unavailable-high-run',
            output: projectedNumber('103'),
            warnings: [],
          },
          impact: null,
          warnings: [],
        },
        {
          target: { kind: 'parameter', parameter_id: 'high-impact' },
          low_case: {
            input_value: { value_type: 'number', value: '8' },
            calculation_run_id: 'high-low-run',
            output: projectedNumber('70'),
            warnings: [],
          },
          high_case: {
            input_value: { value_type: 'number', value: '12' },
            calculation_run_id: 'high-high-run',
            output: projectedNumber('120'),
            warnings: [],
          },
          impact: '50',
          warnings: [],
        },
      ],
    }),
    assumptions,
  );

  assert.deepEqual(
    rows.map((row) => ({
      label: row.label,
      low: row.lowValue,
      current: row.currentValue,
      high: row.highValue,
      lowDelta: row.lowDelta,
      highDelta: row.highDelta,
      lowRunId: row.lowRunId,
      highRunId: row.highRunId,
      unavailableReason: row.unavailableReason,
    })),
    [
      {
        label: 'High impact',
        low: 70,
        current: 100,
        high: 120,
        lowDelta: -30,
        highDelta: 20,
        lowRunId: 'high-low-run',
        highRunId: 'high-high-run',
        unavailableReason: null,
      },
      {
        label: 'Unavailable driver',
        low: null,
        current: 100,
        high: 103,
        lowDelta: null,
        highDelta: 3,
        lowRunId: 'unavailable-low-run',
        highRunId: 'unavailable-high-run',
        unavailableReason: 'blocked',
      },
    ],
  );
});

test('two-way matrix preserves explicit axis order, run IDs, and unavailable cells', () => {
  const assumptions = new Map([
    [
      'parameter:row',
      numericAssumption('row', '10', { label: 'Row driver' }),
    ],
    [
      'parameter:column',
      numericAssumption('column', '20', { label: 'Column driver' }),
    ],
  ]);
  const matrix = buildTwoWayMatrix(
    sensitivityResponse({
      two_way: {
        row_target: { kind: 'parameter', parameter_id: 'row' },
        column_target: { kind: 'parameter', parameter_id: 'column' },
        cells: [
          {
            row_value: { value_type: 'number', value: '12' },
            column_value: { value_type: 'number', value: '22' },
            calculation_run_id: 'cell-12-22',
            output: projectedNumber('5'),
            warnings: [],
          },
          {
            row_value: { value_type: 'number', value: '12' },
            column_value: { value_type: 'number', value: '18' },
            calculation_run_id: 'cell-12-18',
            output: unavailableProjection('unsupported'),
            warnings: [],
          },
          {
            row_value: { value_type: 'number', value: '8' },
            column_value: { value_type: 'number', value: '22' },
            calculation_run_id: 'cell-8-22',
            output: projectedNumber('3'),
            warnings: [],
          },
          {
            row_value: { value_type: 'number', value: '8' },
            column_value: { value_type: 'number', value: '18' },
            calculation_run_id: 'cell-8-18',
            output: projectedNumber('2'),
            warnings: [],
          },
        ],
      },
    }),
    assumptions,
  );

  assert.equal(matrix?.rowLabel, 'Row driver');
  assert.equal(matrix?.columnLabel, 'Column driver');
  assert.deepEqual(matrix?.rowValues, ['12', '8']);
  assert.deepEqual(matrix?.columnValues, ['22', '18']);
  assert.deepEqual(
    matrix?.rows.map((row) =>
      row.cells.map((cell) => ({
        value: cell.numericValue,
        runId: cell.calculationRunId,
        unavailableReason: cell.unavailableReason,
      })),
    ),
    [
      [
        { value: 5, runId: 'cell-12-22', unavailableReason: null },
        {
          value: null,
          runId: 'cell-12-18',
          unavailableReason: 'unsupported',
        },
      ],
      [
        { value: 3, runId: 'cell-8-22', unavailableReason: null },
        { value: 2, runId: 'cell-8-18', unavailableReason: null },
      ],
    ],
  );
});
