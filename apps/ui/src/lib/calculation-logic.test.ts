import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createElement, useState } from 'react';
import TestRenderer, { act } from 'react-test-renderer';

import { FixedSensitivityDashboard } from '../components/sensitivity/FixedSensitivityDashboard';
import { SensitivityAssumptionPanel } from '../components/sensitivity/SensitivityAssumptionPanel';
import { SensitivityTwoWayMatrix } from '../components/sensitivity/SensitivityTwoWayMatrix';

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
  createGuardedSensitivityStorage,
  isCalculationStorageLockAvailable,
  matchesPersistedSensitivityIdentity,
  persistCalculationRunId,
  persistGraphVersionId,
  persistUploadIdentity,
  readPersistedCalculationState,
  readSensitivityWorkbenchDocument,
  reconcileStoredRun,
  shouldAutoRunBaseline,
  type SensitivityWorkbenchLockManager,
  type StorageLike,
} from './calculation-storage';
import {
  diffCalculationRunValues,
  typedValuesEqual,
} from './calculation-value-utils';
import {
  buildSensitivityOutputView,
  estimateSensitivityKpis,
  selectSensitivityRunId,
} from './sensitivity-output-adapter';
import {
  orderFixedDashboardAssumptions,
  promoteFixedDashboardDriver,
  resolveFixedDashboardAnalysis,
  resolveFixedDashboardCalculationMode,
  resolveFixedDashboardTwoWayUnavailableReason,
  resolveFixedDashboardViewModel,
  visibleFixedDashboardAssumptions,
} from './sensitivity-dashboard-view-model';
import {
  buildCanonicalOverrideCalculationRequest,
  buildSensitivityRequest,
  buildTornadoRows,
  buildTwoWayMatrix,
  canApplySensitivityResponse,
  canRetainSensitivityIdentity,
  deriveSliderControlStep,
  deriveSliderSpec,
  formatSensitivityDelta,
  isSensitivityCatalogIdentityError,
  loadAllEditableNumericParameters,
  retainEligibleSensitivityDrivers,
  resolveSensitivitySelections,
  restoreSensitivityOutputProjection,
  selectDefaultSensitivityOutput,
  SensitivityCatalogIdentityError,
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

const immediateLockManager: SensitivityWorkbenchLockManager = {
  async request(_name, _options, callback) {
    return callback();
  },
};

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

test('estimated KPI preview uses piecewise endpoint slopes and adds driver deltas', () => {
  const exact = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'npv-output',
          entity_kind: 'scalar',
          business_role: 'npv',
          label: 'NPV',
          unit: 'USD',
          scenario: null,
          formula_cell_id: 'formula-npv',
          number_format: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          availability_status: 'available',
          baseline: projectedNumber('90'),
          current: projectedNumber('100'),
        },
      ],
    }),
  ).kpis;
  const assumptions = [
    numericAssumption('driver-a', '10'),
    numericAssumption('driver-b', '20'),
  ];
  const caseOutput = (value: string) => ({
    output_id: 'npv-output',
    business_role: 'npv',
    label: 'NPV',
    unit: 'USD',
    scenario: null,
    number_format: null,
    value: projectedNumber(value),
  });
  const analysis = sensitivityResponse({
    current_outputs: [caseOutput('100')],
    drivers: [
      {
        target: assumptions[0].target,
        low_case: {
          case_id: 'a-low',
          input_value: { value_type: 'number', value: '0' },
          calculation_run_id: null,
          output: projectedNumber('80'),
          outputs: [caseOutput('80')],
          warnings: [],
        },
        high_case: {
          case_id: 'a-high',
          input_value: { value_type: 'number', value: '20' },
          calculation_run_id: null,
          output: projectedNumber('140'),
          outputs: [caseOutput('140')],
          warnings: [],
        },
        impact: '60',
        warnings: [],
      },
      {
        target: assumptions[1].target,
        low_case: {
          case_id: 'b-low',
          input_value: { value_type: 'number', value: '10' },
          calculation_run_id: null,
          output: projectedNumber('90'),
          outputs: [caseOutput('90')],
          warnings: [],
        },
        high_case: {
          case_id: 'b-high',
          input_value: { value_type: 'number', value: '30' },
          calculation_run_id: null,
          output: projectedNumber('130'),
          outputs: [caseOutput('130')],
          warnings: [],
        },
        impact: '40',
        warnings: [],
      },
    ],
  });

  const preview = estimateSensitivityKpis({
    kpis: exact,
    analysis,
    assumptions,
    analysisOverridesByTarget: {},
    previewOverridesByTarget: {
      'parameter:driver-a': '15',
      'parameter:driver-b': '25',
    },
  });

  assert.deepEqual(preview.estimatedOutputIds, ['npv-output']);
  assert.equal(preview.kpis[0].current.numericValue, 135);
  assert.equal(preview.kpis[0].absoluteChange, 45);
});

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

test('new uploads clear only calculation graph and run state', async () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.workbookVersionId, 'old-workbook');
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'old-model');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'old-graph');
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'old-baseline');
  storage.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'old-override');
  storage.setItem('investiq_model_id', 'legacy-model');

  await clearCalculationArtifacts(storage, immediateLockManager);
  await persistUploadIdentity(
    storage,
    uploadResponse(),
    immediateLockManager,
  );

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

test('calculation storage lock capability is explicit before mutation', () => {
  assert.equal(isCalculationStorageLockAvailable(null), false);
  assert.equal(
    isCalculationStorageLockAvailable(immediateLockManager),
    true,
  );
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

test('stale run IDs are cleared without mixing model or graph values', async () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'stale-run');
  const expectedIdentity = readPersistedCalculationState(storage);

  const result = await reconcileStoredRun(
    storage,
    'baseline',
    runResponse({
      calculation_run_id: 'stale-run',
      model_version_id: 'different-model',
    }),
    'model-version',
    'graph-version',
    expectedIdentity,
    immediateLockManager,
  );

  assert.equal(result.isCurrent, false);
  assert.equal(result.notice?.includes('different model or graph'), true);
  assert.equal(storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId), null);
});

test('parallel reload cannot apply a run removed by earlier cleanup', async () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'graph-version');
  const expectedIdentity = readPersistedCalculationState(storage);

  const result = await reconcileStoredRun(
    storage,
    'override',
    runResponse({ calculation_run_id: 'removed-override-run' }),
    'model-version',
    'graph-version',
    expectedIdentity,
    immediateLockManager,
  );

  assert.equal(result.isCurrent, false);
  assert.equal(result.disposition, 'conflict');
  assert.match(result.notice ?? '', /no longer the selected persisted run/);
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

test('calculation panel rejects stale async storage writers before mutation', () => {
  const panelSource = readFileSync(
    'src/components/calculation/CalculationPreparationPanel.tsx',
    'utf8',
  );
  const identityGuardIndex = panelSource.indexOf(
    'if (!identityMatches)',
  );
  const graphPersistenceIndex = panelSource.indexOf(
    'const graphPersisted = await persistGraphVersionId',
  );

  assert.ok(identityGuardIndex >= 0);
  assert.ok(graphPersistenceIndex > identityGuardIndex);
  assert.match(
    panelSource,
    /const expectedIdentity = readPersistedCalculationState\([\s\S]*await getCalculationReadiness\(modelVersionId\)[\s\S]*activateReadyCalculation\(\s*response,\s*requestRevision,\s*expectedIdentity,/,
  );
  assert.match(
    panelSource,
    /const expectedIdentity = readPersistedCalculationState\([\s\S]*await prepareCalculation\(modelVersionId\)[\s\S]*activateReadyCalculation\(\s*response,\s*requestRevision,\s*expectedIdentity,/,
  );
  assert.match(
    panelSource,
    /persistGraphVersionId\(\s*window\.localStorage,\s*targetGraphVersionId,\s*expectedIdentity,/,
  );
  assert.match(
    panelSource,
    /expectedIdentity\.baselineRunId !== null \|\|[\s\S]*expectedIdentity\.overrideRunId !== null/,
  );
  assert.match(
    panelSource,
    /reconciled\.disposition === 'conflict'[\s\S]*setStateNotice\(reconciled\.notice\);[\s\S]*return;/,
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
  const dashboard = resolveFixedDashboardViewModel(view.kpis);
  const irrSlot = dashboard.slots.find((slot) => slot.key === 'irr');
  assert.equal(irrSlot?.kpi?.outputId, 'equity-irr-output');
  assert.equal(irrSlot?.unavailable, true);
  assert.match(
    (irrSlot as { unavailableDetail?: string } | undefined)
      ?.unavailableDetail ?? '',
    /unsupported/,
  );
  assert.equal(dashboard.irrOutputId, null);
});

test('fixed dashboard includes typed engine errors in unavailable KPI detail', () => {
  const failedIrr = {
    ...unavailableProjection('execution_error'),
    engine_error_code: '#NUM!',
  };
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'project-irr-error',
          entity_kind: 'scalar',
          business_role: 'project_irr',
          label: 'Project IRR',
          unit: '%',
          scenario: null,
          formula_cell_id: 'formula-project-irr',
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0%',
          availability_status: 'unavailable',
          baseline: failedIrr,
          current: failedIrr,
        },
      ],
    }),
  );

  assert.equal(view.kpis[0].current.engineErrorCode, '#NUM!');
  const dashboard = resolveFixedDashboardViewModel(view.kpis);
  const irrSlot = dashboard.slots.find((slot) => slot.key === 'irr');
  assert.match(irrSlot?.unavailableDetail ?? '', /#NUM!/);
  assert.match(irrSlot?.unavailableDetail ?? '', /execution_error/);
});

test('fixed dashboard keeps five controlled KPI slots and resolves only approved numeric roles', () => {
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'project-irr-unavailable',
          entity_kind: 'scalar',
          business_role: 'project_irr',
          label: 'Project return in workbook',
          unit: '%',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'unsupported',
          number_format: '0.0%',
          availability_status: 'unavailable',
          baseline: unavailableProjection('blocked'),
          current: unavailableProjection('blocked'),
        },
        {
          output_id: 'equity-irr-output',
          entity_kind: 'scalar',
          business_role: 'equity_irr',
          label: 'Owner return',
          unit: '%',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0%',
          availability_status: 'available',
          baseline: projectedNumber('0.1'),
          current: projectedNumber('0.12'),
        },
        {
          output_id: 'npv-output',
          entity_kind: 'scalar',
          business_role: 'npv',
          label: 'Net present value',
          unit: 'USD M',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0',
          availability_status: 'available',
          baseline: projectedNumber('100'),
          current: projectedNumber('120'),
        },
        {
          output_id: 'payback-output',
          entity_kind: 'scalar',
          business_role: 'payback_period',
          label: 'Payback period',
          unit: 'years',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'blocked',
          number_format: '0.0',
          availability_status: 'unavailable',
          baseline: unavailableProjection('blocked formula'),
          current: unavailableProjection('blocked formula'),
        },
        {
          output_id: 'misleading-output',
          entity_kind: 'scalar',
          business_role: 'free_cash_flow',
          label: 'IRR and DSCR headline',
          unit: '%',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0%',
          availability_status: 'available',
          baseline: projectedNumber('0.3'),
          current: projectedNumber('0.31'),
        },
      ],
    }),
  );

  const dashboard = resolveFixedDashboardViewModel(
    view.kpis,
    'npv-output',
  );

  assert.deepEqual(
    dashboard.slots.map((slot) => ({
      key: slot.key,
      outputId: slot.kpi?.outputId ?? null,
      label: slot.displayLabel,
      unavailable: slot.unavailable,
    })),
    [
      {
        key: 'irr',
        outputId: 'equity-irr-output',
        label: 'IRR · Equity IRR',
        unavailable: false,
      },
      {
        key: 'npv',
        outputId: 'npv-output',
        label: 'NPV',
        unavailable: false,
      },
      {
        key: 'payback',
        outputId: 'payback-output',
        label: 'Payback',
        unavailable: true,
      },
      { key: 'dscr', outputId: null, label: 'DSCR', unavailable: true },
      {
        key: 'equity_multiple',
        outputId: null,
        label: 'Equity ×',
        unavailable: true,
      },
    ],
  );
  assert.equal(dashboard.irrOutputId, 'equity-irr-output');
});

test('fixed dashboard assumption helpers preserve canonical order, impact ranking, cap, and deterministic promotion', () => {
  const assumptions = Array.from({ length: 14 }, (_, index) =>
    numericAssumption(`driver-${index + 1}`, `${index + 1}.000`),
  );

  assert.deepEqual(
    visibleFixedDashboardAssumptions(assumptions, false).map(
      (assumption) => assumption.targetKey,
    ),
    assumptions.slice(0, 8).map((assumption) => assumption.targetKey),
  );
  assert.deepEqual(
    visibleFixedDashboardAssumptions(assumptions, true).map(
      (assumption) => assumption.targetKey,
    ),
    assumptions.map((assumption) => assumption.targetKey),
  );
  assert.deepEqual(
    orderFixedDashboardAssumptions(assumptions, [
      { targetKey: 'parameter:driver-3', impact: 2 },
      { targetKey: 'parameter:driver-1', impact: 2 },
      { targetKey: 'parameter:driver-2', impact: 5 },
    ]).slice(0, 4).map((assumption) => assumption.targetKey),
    [
      'parameter:driver-2',
      'parameter:driver-1',
      'parameter:driver-3',
      'parameter:driver-4',
    ],
  );
  assert.deepEqual(
    promoteFixedDashboardDriver({
      assumptions,
      currentDriverKeys: assumptions.slice(0, 12).map((assumption) => assumption.targetKey),
      changedTargetKey: 'parameter:driver-13',
      impactsByTarget: {
        'parameter:driver-1': 7,
        'parameter:driver-2': 1,
      },
    }),
    [
      'parameter:driver-1',
      'parameter:driver-3',
      'parameter:driver-4',
      'parameter:driver-5',
      'parameter:driver-6',
      'parameter:driver-7',
      'parameter:driver-8',
      'parameter:driver-9',
      'parameter:driver-10',
      'parameter:driver-11',
      'parameter:driver-12',
      'parameter:driver-13',
    ],
  );
  assert.deepEqual(
    promoteFixedDashboardDriver({
      assumptions,
      currentDriverKeys: assumptions.slice(0, 12).map((assumption) => assumption.targetKey),
      changedTargetKey: 'parameter:driver-14',
      impactsByTarget: {},
    }).slice(-2),
    ['parameter:driver-11', 'parameter:driver-14'],
  );
});

test('fixed dashboard renders the stable workbench, eight default sliders, and no output or axis selectors', () => {
  const outputView = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'project-irr-output',
          entity_kind: 'scalar',
          business_role: 'project_irr',
          label: 'Project return',
          unit: '%',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0%',
          availability_status: 'available',
          baseline: projectedNumber('0.1'),
          current: projectedNumber('0.12'),
        },
        {
          output_id: 'npv-output',
          entity_kind: 'scalar',
          business_role: 'npv',
          label: 'Net present value',
          unit: 'USD M',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0',
          availability_status: 'available',
          baseline: projectedNumber('100'),
          current: projectedNumber('120'),
        },
        {
          output_id: 'payback-render-output',
          entity_kind: 'scalar',
          business_role: 'payback_period',
          label: 'Payback period',
          unit: 'years',
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'blocked',
          number_format: '0.0',
          availability_status: 'unavailable',
          baseline: unavailableProjection('blocked formula'),
          current: unavailableProjection('blocked formula'),
        },
      ],
    }),
  );
  const assumptions = Array.from({ length: 10 }, (_, index) => ({
    ...numericAssumption(`driver-${index + 1}`, `${index + 1}`),
    label: `Model assumption ${index + 1}`,
  }));
  let expandRequested = false;
  let renderer!: TestRenderer.ReactTestRenderer;

  act(() => {
    renderer = TestRenderer.create(
      createElement(FixedSensitivityDashboard, {
        dashboard: resolveFixedDashboardViewModel(outputView.kpis),
        assumptions,
        overridesByTarget: {},
        tornadoRows: [],
        matrix: null,
        expanded: false,
        recalculating: false,
        errorMessage: null,
        controlsDisabled: false,
        calculationRunId: outputView.calculationRunId,
        analysisOutputLabel: 'IRR',
        analysisUnavailableReason: null,
        twoWayUnavailableReason: null,
        onToggleExpanded: () => {
          expandRequested = true;
        },
        onValueChange: () => {},
        onReset: () => {},
        onResetAll: () => {},
        onRefresh: () => {},
        formatAxisValue: (_targetKey: string, value: string) => value,
        formatAnalyzedOutputValue: (value: number | null) =>
          value === null ? 'Unavailable' : String(value),
        formatAnalyzedOutputDelta: (value: number) => String(value),
      }),
    );
  });

  const renderedText = JSON.stringify(renderer.toJSON());
  assert.match(renderedText, /Decision Confidence/);
  assert.match(renderedText, /Threshold unavailable/);
  assert.match(renderedText, /Live Model KPIs/);
  assert.match(renderedText, /Assumption sliders/);
  assert.match(renderedText, /IRR tornado chart/);
  assert.match(renderedText, /Scenario comparison/);
  assert.match(renderedText, /Two-way sensitivity/);
  assert.match(renderedText, /Current Assumptions/);
  assert.match(renderedText, /blocked formula/);
  assert.doesNotMatch(renderedText, /Canonical time-series outputs/);
  assert.equal(
    renderer.root.findAll(
      (node) =>
        node.type === 'article' &&
        node.props['data-testid'] === 'fixed-kpi-card',
    ).length,
    5,
  );
  assert.equal(
    renderer.root.findAll(
      (node) =>
        node.type === 'input' &&
        String(node.props.id ?? '').startsWith('assumption-'),
    ).length,
    8,
  );
  assert.equal(
    renderer.root.findAll((node) => node.type === 'select').length,
    0,
  );
  const sensitivityControls = renderer.root.findByProps({
    'data-testid': 'fixed-sensitivity-controls',
  });
  assert.equal(
    sensitivityControls.findAllByProps({
      'aria-label': 'Refresh persisted results',
    }).length,
    0,
  );
  assert.equal(
    renderer.root.findAllByProps({
      'aria-label': 'Refresh persisted results',
    }).length,
    1,
  );
  assert.doesNotMatch(renderedText, /Select two distinct/);
  const expandButton = renderer.root.findByProps({
    'aria-label': 'Show all 10 assumptions',
  });
  act(() => {
    expandButton.props.onClick();
  });
  assert.equal(expandRequested, true);

  act(() => {
    renderer.update(
      createElement(FixedSensitivityDashboard, {
        dashboard: resolveFixedDashboardViewModel(outputView.kpis),
        assumptions,
        overridesByTarget: {},
        tornadoRows: [],
        matrix: null,
        expanded: true,
        recalculating: false,
        errorMessage: 'Backend failed',
        controlsDisabled: false,
        calculationRunId: outputView.calculationRunId,
        analysisOutputLabel: 'IRR',
        analysisUnavailableReason: null,
        twoWayUnavailableReason: null,
        onToggleExpanded: () => {},
        onValueChange: () => {},
        onReset: () => {},
        onResetAll: () => {},
        onRefresh: () => {},
        formatAxisValue: (_targetKey: string, value: string) => value,
        formatAnalyzedOutputValue: (value: number | null) =>
          value === null ? 'Unavailable' : String(value),
        formatAnalyzedOutputDelta: (value: number) => String(value),
      }),
    );
  });
  assert.equal(
    renderer.root.findAll(
      (node) =>
        node.type === 'input' &&
        String(node.props.id ?? '').startsWith('assumption-'),
    ).length,
    10,
  );
  assert.match(
    JSON.stringify(renderer.toJSON()),
    /Last successful result retained/,
  );
  act(() => {
    renderer.unmount();
  });
});

test('fixed dashboard uses ordinary calculation only when IRR sensitivity cannot run', () => {
  assert.equal(
    resolveFixedDashboardCalculationMode('project-irr-output', 2),
    'sensitivity',
  );
  assert.equal(
    resolveFixedDashboardCalculationMode('equity-irr-output', 1),
    'sensitivity',
  );
  assert.equal(
    resolveFixedDashboardCalculationMode('project-irr-output', 0),
    'calculation',
  );
  assert.equal(resolveFixedDashboardCalculationMode(null, 8), 'calculation');
  assert.equal(resolveFixedDashboardCalculationMode(null, 0), 'calculation');
});

test('fixed dashboard discards an analysis when the resolved IRR output role changes', () => {
  const projectIrrAnalysis = sensitivityResponse();

  assert.strictEqual(
    resolveFixedDashboardAnalysis(
      projectIrrAnalysis,
      'project-irr-output',
    ),
    projectIrrAnalysis,
  );
  assert.equal(
    resolveFixedDashboardAnalysis(
      projectIrrAnalysis,
      'equity-irr-output',
    ),
    null,
  );
  assert.equal(
    resolveFixedDashboardAnalysis(projectIrrAnalysis, null),
    null,
  );
});

test('fixed dashboard surfaces the typed top-impact warning when no matrix is returned', () => {
  const warning =
    'TOP_IMPACT_TWO_WAY_UNAVAILABLE: Fewer than two drivers returned usable IRR impacts, so no two-way matrix was generated.';
  const response = sensitivityResponse({
    warnings: ['TOP_IMPACT_TWO_WAY_UNAVAILABLE'],
    two_way: null,
  });

  assert.equal(
    resolveFixedDashboardTwoWayUnavailableReason(response),
    warning,
  );
  assert.equal(
    resolveFixedDashboardTwoWayUnavailableReason(
      sensitivityResponse({ warnings: [] }),
    ),
    null,
  );

  let renderer!: TestRenderer.ReactTestRenderer;
  act(() => {
    renderer = TestRenderer.create(
      createElement(SensitivityTwoWayMatrix, {
        matrix: null,
        outputLabel: 'IRR',
        unavailableReason: warning,
        formatAxisValue: (_targetKey: string, value: string) => value,
        formatOutputValue: (value: number | null) =>
          value === null ? 'Unavailable' : String(value),
      }),
    );
  });
  const renderedText = JSON.stringify(renderer.toJSON());
  assert.match(renderedText, /TOP_IMPACT_TWO_WAY_UNAVAILABLE/);
  assert.doesNotMatch(renderedText, /Run an analysis/);
  act(() => {
    renderer.unmount();
  });
});

test('assumption panel renders eight compact desktop rows with controls kept together', () => {
  const assumptions = Array.from({ length: 8 }, (_, index) =>
    numericAssumption(`compact-driver-${index + 1}`, `${index + 1}`, {
      label: `Compact driver ${index + 1}`,
      category: 'Operating assumptions',
      unit: index === 0 ? '%' : null,
    }),
  );
  let renderer!: TestRenderer.ReactTestRenderer;

  act(() => {
    renderer = TestRenderer.create(
      createElement(SensitivityAssumptionPanel, {
        assumptions,
        overridesByTarget: {},
        onValueChange: () => {},
        onReset: () => {},
        onResetAll: () => {},
      }),
    );
  });

  const rows = renderer.root.findAllByProps({
    'data-testid': 'sensitivity-assumption-row',
  });
  assert.equal(rows.length, 8);
  for (const [index, row] of rows.entries()) {
    assert.match(row.props.className, /\bgrid\b/);
    assert.match(row.props.className, /\bmd:grid-cols-/);
    assert.doesNotMatch(row.props.className, /\bp-3\b/);
    assert.equal(
      row.findAllByProps({
        id: `assumption-${assumptions[index].targetKey}`,
      }).length,
      1,
    );
    assert.equal(
      row.findAllByProps({
        'aria-label': `Reset ${assumptions[index].label}`,
      }).length,
      1,
    );
  }
  assert.match(JSON.stringify(renderer.toJSON()), /100 %/);

  act(() => {
    renderer.unmount();
  });
});

test('expanded assumption sliders keep the eight-row card height and scroll the extra rows', () => {
  const assumptions = Array.from({ length: 10 }, (_, index) =>
    numericAssumption(`fixed-height-driver-${index + 1}`, `${index + 1}`, {
      label: `Fixed height driver ${index + 1}`,
      category: 'Operating assumptions',
    }),
  );
  function SensitivityDashboardHarness() {
    const [expanded, setExpanded] = useState(false);
    return createElement(FixedSensitivityDashboard, {
      dashboard: resolveFixedDashboardViewModel([]),
      assumptions,
      overridesByTarget: {},
      tornadoRows: [],
      matrix: null,
      expanded,
      recalculating: false,
      errorMessage: null,
      controlsDisabled: false,
      calculationRunId: 'fixed-height-run',
      analysisOutputLabel: 'IRR',
      analysisUnavailableReason: null,
      twoWayUnavailableReason: null,
      onToggleExpanded: () => setExpanded((current) => !current),
      onValueChange: () => {},
      onReset: () => {},
      onResetAll: () => {},
      onRefresh: () => {},
      formatAxisValue: (_targetKey: string, value: string) => value,
      formatAnalyzedOutputValue: (value: number | null) =>
        value === null ? 'Unavailable' : String(value),
      formatAnalyzedOutputDelta: (value: number) => String(value),
    });
  }
  const scrollRegionElement = { scrollTop: 0 };
  let renderer!: TestRenderer.ReactTestRenderer;

  act(() => {
    renderer = TestRenderer.create(createElement(SensitivityDashboardHarness), {
      createNodeMock: (element) =>
        element.props['data-testid'] ===
        'fixed-sensitivity-assumption-scroll-region'
          ? scrollRegionElement
          : {},
    });
  });
  const collapsedCard = renderer.root.findByProps({
    'data-testid': 'fixed-sensitivity-assumption-card',
  });
  const collapsedHeight = collapsedCard.props.className;
  assert.match(collapsedHeight, /h-\[38rem\]/);
  assert.equal(
    renderer.root.findAllByProps({
      'data-testid': 'fixed-sensitivity-assumption-scroll-region',
    }).length,
    1,
  );
  assert.equal(
    renderer.root.findAllByProps({
      'data-testid': 'sensitivity-assumption-row',
    }).length,
    8,
  );

  act(() => {
    renderer.root
      .findByProps({ 'aria-label': 'Show all 10 assumptions' })
      .props.onClick();
  });
  const expandedCard = renderer.root.findByProps({
    'data-testid': 'fixed-sensitivity-assumption-card',
  });
  const scrollRegion = renderer.root.findByProps({
    'data-testid': 'fixed-sensitivity-assumption-scroll-region',
  });
  assert.equal(expandedCard.props.className, collapsedHeight);
  assert.match(scrollRegion.props.className, /\boverflow-y-auto\b/);
  assert.match(scrollRegion.props.className, /\bmin-h-0\b/);
  assert.equal(
    scrollRegion.findAllByProps({
      'data-testid': 'sensitivity-assumption-row',
    }).length,
    10,
  );
  assert.equal(
    renderer.root.findAllByProps({
      'aria-label': 'Show first 8 assumptions',
    }).length,
    1,
  );
  scrollRegionElement.scrollTop = 240;

  act(() => {
    renderer.root
      .findByProps({ 'aria-label': 'Show first 8 assumptions' })
      .props.onClick();
  });
  assert.equal(
    scrollRegionElement.scrollTop,
    0,
    'collapsing returns the slider viewport to its first focused control',
  );
  assert.equal(
    renderer.root.findAllByProps({
      'data-testid': 'sensitivity-assumption-row',
    }).length,
    8,
  );

  act(() => {
    renderer.unmount();
  });
});

test('two-way matrix keeps case provenance on cells without offscreen descendants', () => {
  let renderer!: TestRenderer.ReactTestRenderer;

  act(() => {
    renderer = TestRenderer.create(
      createElement(SensitivityTwoWayMatrix, {
        matrix: {
          rowTargetKey: 'parameter:row',
          columnTargetKey: 'parameter:column',
          rowLabel: 'Row driver',
          columnLabel: 'Column driver',
          rowValues: ['10'],
          columnValues: ['20'],
          rows: [
            {
              value: '10',
              cells: [
                {
                  rowValue: '10',
                  columnValue: '20',
                  calculationRunId: 'matrix-case-run',
                  numericValue: 0.12,
                  unavailableReason: null,
                  warnings: ['reviewed'],
                },
              ],
            },
          ],
        },
        outputLabel: 'Project IRR',
        formatAxisValue: (_targetKey: string, value: string) => value,
        formatOutputValue: (value: number | null) =>
          value === null ? 'Unavailable' : `${value * 100}%`,
      }),
    );
  });

  const cell = renderer.root.findByType('td');
  assert.match(cell.props.className, /\bpy-2\b/);
  assert.doesNotMatch(cell.props.className, /\bpy-3\b/);
  assert.equal(cell.findAllByType('details').length, 0);
  assert.equal(
    cell.findAllByProps({
      'data-testid': 'sensitivity-matrix-cell-provenance',
    }).length,
    0,
  );
  assert.match(cell.props.title, /Run matrix-case-run/);
  assert.match(cell.props.title, /reviewed/);
  assert.match(cell.props['aria-label'], /Run matrix-case-run/);
  assert.match(cell.props['aria-label'], /reviewed/);

  act(() => {
    renderer.unmount();
  });
});

test('ordinary fixed-dashboard calculation submits the complete canonical override set', () => {
  const assumptions = [
    numericAssumption('driver-1', '10'),
    numericAssumption('driver-2', '20'),
    numericAssumption('driver-3', '30'),
  ];

  assert.deepEqual(
    buildCanonicalOverrideCalculationRequest({
      graphVersionId: 'graph-version',
      assumptions,
      overridesByTarget: {
        [assumptions[0].targetKey]: '11.5',
        [assumptions[1].targetKey]: '18',
      },
    }),
    {
      graph_version_id: 'graph-version',
      overrides: [
        {
          target: assumptions[0].target,
          value: { value_type: 'number', value: '11.5' },
        },
        {
          target: assumptions[1].target,
          value: { value_type: 'number', value: '18' },
        },
      ],
      idempotency_key: null,
    },
  );
});

test('partial outputs preserve baseline and current unavailability independently', () => {
  const view = buildSensitivityOutputView(
    runOutputsResponse({
      outputs: [
        {
          output_id: 'partial-project-irr-output',
          entity_kind: 'scalar',
          business_role: 'project_irr',
          label: 'Project IRR',
          unit: '%',
          scenario: null,
          formula_cell_id: 'formula-project-irr',
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: '0.0%',
          availability_status: 'partial',
          baseline: unavailableProjection('baseline blocked'),
          current: projectedNumber('0.12'),
        },
        {
          output_id: 'partial-revenue-output',
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
              financial_series_value_id: 'revenue-2027',
              period_index: 0,
              period: '2027',
              formula_cell_id: 'formula-revenue-2027',
              mapping_status: 'mapped',
              support_status: 'supported',
              number_format: '0.0',
              availability_status: 'partial',
              baseline: unavailableProjection('baseline blocked'),
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
              availability_status: 'partial',
              baseline: projectedNumber('110'),
              current: unavailableProjection('current blocked'),
            },
          ],
        },
      ],
    }),
  );

  assert.equal(view.kpis[0].availabilityStatus, 'partial');
  assert.equal(
    view.kpis[0].baseline.unavailableReason,
    'baseline blocked',
  );
  assert.equal(view.kpis[0].current.unavailableReason, null);
  assert.equal(view.kpis[0].absoluteChange, null);
  assert.equal(view.kpis[0].percentageChange, null);

  const sideAvailability = view.series[0] as unknown as Record<
    string,
    unknown
  >;
  assert.deepEqual(
    {
      baselineCount: sideAvailability.unavailableBaselinePointCount,
      baselineReasons: sideAvailability.unavailableBaselineReasons,
      currentCount: sideAvailability.unavailableCurrentPointCount,
      currentReasons: sideAvailability.unavailableCurrentReasons,
    },
    {
      baselineCount: 1,
      baselineReasons: ['baseline blocked'],
      currentCount: 1,
      currentReasons: ['current blocked'],
    },
  );
  assert.equal(view.series[0].points[0].absoluteChange, null);
  assert.equal(view.series[0].points[1].absoluteChange, null);
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

test('canonical sensitivity API preserves a legacy explicit request without a mode field', async () => {
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
    'graph-version',
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

test('canonical input pagination rejects stale model or graph pages', async () => {
  const page = {
    model_version_id: 'model-version',
    graph_version_id: 'graph-version',
    inputs: [],
    next_cursor: null,
  };

  await assert.rejects(
    () =>
      loadAllEditableNumericParameters(
        'model-version',
        async () => ({ ...page, model_version_id: 'other-model' }),
        'graph-version',
      ),
    (caught) =>
      caught instanceof SensitivityCatalogIdentityError &&
      caught.identityKind === 'model' &&
      isSensitivityCatalogIdentityError(caught),
  );
  await assert.rejects(
    () =>
      loadAllEditableNumericParameters(
        'model-version',
        async () => ({ ...page, graph_version_id: 'other-graph' }),
        'graph-version',
      ),
    (caught) =>
      caught instanceof SensitivityCatalogIdentityError &&
      caught.identityKind === 'graph' &&
      isSensitivityCatalogIdentityError(caught),
  );
});

test('catalog identity mismatch is distinct from transport and cursor failures', async () => {
  const networkError = new Error('network unavailable');
  await assert.rejects(
    () =>
      loadAllEditableNumericParameters(
        'model-version',
        async () => {
          throw networkError;
        },
        'graph-version',
      ),
    (caught) =>
      caught === networkError &&
      !isSensitivityCatalogIdentityError(caught),
  );

  let calls = 0;
  await assert.rejects(
    () =>
      loadAllEditableNumericParameters(
        'model-version',
        async () => {
          calls += 1;
          return {
            model_version_id: 'model-version',
            graph_version_id: 'graph-version',
            inputs: [],
            next_cursor: 'repeated-cursor',
          };
        },
        'graph-version',
      ),
    (caught) =>
      caught instanceof Error &&
      /repeated cursor/.test(caught.message) &&
      !isSensitivityCatalogIdentityError(caught),
  );
  assert.equal(calls, 2);
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

test('range controls preserve persisted overrides by refining the suggested step grid', () => {
  const yearSlider = deriveSliderSpec('2026');
  assert.equal(yearSlider.kind, 'range');
  if (yearSlider.kind !== 'range') {
    return;
  }
  assert.equal(deriveSliderControlStep(yearSlider, '2026'), '8.104');
  assert.equal(deriveSliderControlStep(yearSlider, '1620.8'), '8.104');
  assert.equal(deriveSliderControlStep(yearSlider, '2030'), '0.008');
  assert.equal(deriveSliderControlStep(yearSlider, '2.03e3'), '0.008');
  assert.equal(deriveSliderControlStep(yearSlider, '3000'), null);

  const priceSlider = deriveSliderSpec('100');
  assert.equal(priceSlider.kind, 'range');
  if (priceSlider.kind !== 'range') {
    return;
  }
  assert.equal(deriveSliderControlStep(priceSlider, '99.5'), '0.1');
  assert.equal(
    deriveSliderControlStep(priceSlider, '100.000001'),
    null,
  );

  const negativeSlider = deriveSliderSpec('-50');
  assert.equal(negativeSlider.kind, 'range');
  if (negativeSlider.kind !== 'range') {
    return;
  }
  assert.equal(
    deriveSliderControlStep(negativeSlider, '-49.9'),
    '0.1',
  );

  const fractionalSlider = deriveSliderSpec('0.1');
  assert.equal(fractionalSlider.kind, 'range');
  if (fractionalSlider.kind !== 'range') {
    return;
  }
  assert.equal(
    deriveSliderControlStep(fractionalSlider, '1.005e-1'),
    '0.0001',
  );

  const panelSource = readFileSync(
    'src/components/sensitivity/SensitivityAssumptionPanel.tsx',
    'utf8',
  );

  assert.match(
    panelSource,
    /const sliderControlStep =[\s\S]*deriveSliderControlStep\(sliderSpec, value\)/,
  );
  assert.match(panelSource, /sliderControlStep !== null/);
  assert.match(panelSource, /step=\{sliderControlStep\}/);
});

test('fallback number control stays focused through decimal editing and returns to a valid range on blur', () => {
  const assumption: SensitivityAssumption = {
    targetKey: 'parameter:11111111-1111-4111-8111-111111111111',
    target: {
      kind: 'parameter',
      parameter_id: '11111111-1111-4111-8111-111111111111',
    },
    label: 'Construction cost',
    category: 'Costs',
    unit: 'USD',
    scenario: null,
    period: null,
    currentValue: '100',
  };
  let changedValue = '';
  const renderPanel = (value: string) =>
    createElement(SensitivityAssumptionPanel, {
      assumptions: [assumption],
      overridesByTarget: {
        [assumption.targetKey]: value,
      },
      onValueChange: (_targetKey: string, nextValue: string) => {
        changedValue = nextValue;
      },
      onReset: () => {},
      onResetAll: () => {},
    });

  let renderer!: TestRenderer.ReactTestRenderer;
  act(() => {
    renderer = TestRenderer.create(renderPanel('100.000001'));
  });
  let valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'number');
  assert.equal(valueInput.props.step, 'any');

  act(() => {
    valueInput.props.onFocus();
    valueInput.props.onChange({ target: { value: '99' } });
    renderer.update(renderPanel('99'));
  });
  assert.equal(changedValue, '99');
  valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'number');

  act(() => {
    valueInput.props.onChange({ target: { value: '99.5' } });
    renderer.update(renderPanel('99.5'));
  });
  valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'number');
  assert.equal(valueInput.props.value, '99.5');

  act(() => {
    valueInput.props.onBlur();
  });
  valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'range');
  assert.equal(valueInput.props.value, '99.5');
  assert.equal(valueInput.props.step, '0.1');

  act(() => {
    renderer.unmount();
  });
});

test('fallback number control keeps intermediate drafts local and emits only finite decimals', () => {
  const assumption: SensitivityAssumption = {
    targetKey: 'parameter:22222222-2222-4222-8222-222222222222',
    target: {
      kind: 'parameter',
      parameter_id: '22222222-2222-4222-8222-222222222222',
    },
    label: 'Debt amount',
    category: 'Financing',
    unit: 'USD',
    scenario: null,
    period: null,
    currentValue: '0',
  };
  const emittedValues: string[] = [];
  const renderPanel = (override: string | null) =>
    createElement(SensitivityAssumptionPanel, {
      assumptions: [assumption],
      overridesByTarget:
        override === null
          ? {}
          : { [assumption.targetKey]: override },
      onValueChange: (_targetKey: string, nextValue: string) => {
        emittedValues.push(nextValue);
      },
      onReset: () => {},
      onResetAll: () => {},
    });

  let renderer!: TestRenderer.ReactTestRenderer;
  act(() => {
    renderer = TestRenderer.create(renderPanel(null));
  });
  let valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'number');
  assert.equal(valueInput.props.step, 'any');

  act(() => {
    valueInput.props.onFocus();
  });
  for (const draft of ['', '-', '.', '1e', '1e-']) {
    act(() => {
      valueInput.props.onChange({ target: { value: draft } });
    });
    valueInput = renderer.root.findByProps({
      id: `assumption-${assumption.targetKey}`,
    });
    assert.equal(valueInput.props.value, draft);
  }
  assert.deepEqual(emittedValues, []);

  act(() => {
    valueInput.props.onChange({ target: { value: '.5' } });
  });
  valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.value, '.5');
  assert.deepEqual(emittedValues, ['0.5']);

  act(() => {
    renderer.update(renderPanel('0.5'));
  });
  valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'number');
  assert.equal(valueInput.props.value, '.5');

  act(() => {
    valueInput.props.onBlur();
  });
  valueInput = renderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'range');
  assert.equal(valueInput.props.value, '0.5');

  act(() => {
    renderer.unmount();
  });

  let invalidRenderer!: TestRenderer.ReactTestRenderer;
  act(() => {
    invalidRenderer = TestRenderer.create(renderPanel(null));
  });
  valueInput = invalidRenderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  act(() => {
    valueInput.props.onFocus();
    valueInput.props.onChange({ target: { value: '-' } });
  });
  valueInput = invalidRenderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.value, '-');

  act(() => {
    valueInput.props.onBlur();
  });
  valueInput = invalidRenderer.root.findByProps({
    id: `assumption-${assumption.targetKey}`,
  });
  assert.equal(valueInput.props.type, 'number');
  assert.equal(valueInput.props.value, '0');
  assert.deepEqual(emittedValues, ['0.5']);

  act(() => {
    invalidRenderer.unmount();
  });
});

test('sensitivity deltas use percentage points and preserve other output units', () => {
  assert.equal(formatSensitivityDelta(0.01, '%', null), '+1 pp');
  assert.equal(formatSensitivityDelta(-1250, 'USD', null), '-1,250 USD');
  assert.equal(formatSensitivityDelta(2.5, null, null), '+2.5');
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
          output_id: 'npv-output-second',
          entity_kind: 'scalar',
          business_role: 'npv',
          label: 'NPV later in display order',
          unit: null,
          scenario: null,
          formula_cell_id: null,
          mapping_status: 'mapped',
          support_status: 'supported',
          number_format: null,
          availability_status: 'available',
          baseline: projectedNumber('5'),
          current: projectedNumber('6'),
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

test('sensitivity request uses canonical targets, changed overrides, driver cap, and top-impact mode', () => {
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
  assert.equal(request.two_way_mode, 'top_impact');
  assert.equal(request.two_way, null);
  assert.doesNotMatch(JSON.stringify(request), /sheet_name|cell_address|cell:/);
});

test('one-driver request uses explicit mode and omits axes regardless of stored selections', () => {
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

  const request = buildSensitivityRequest({
    ...common,
    rowDriverKey: null,
    columnDriverKey: 'parameter:one',
  });
  assert.equal(request.two_way_mode, 'explicit');
  assert.equal(request.two_way, null);
  assert.equal(
    buildSensitivityRequest({
      ...common,
      rowDriverKey: 'parameter:one',
      columnDriverKey: 'parameter:one',
    }).two_way_mode,
    'explicit',
  );
  assert.equal(
    buildSensitivityRequest({
      ...common,
      rowDriverKey: 'parameter:zero',
      columnDriverKey: 'parameter:one',
    }).two_way_mode,
    'explicit',
  );
});

test('stored driver and axis selections require current non-zero effective values', () => {
  const assumptions = [
    numericAssumption('zero', '0'),
    numericAssumption('one', '1'),
    numericAssumption('two', '2'),
  ];
  assert.deepEqual(
    resolveSensitivitySelections({
      assumptions,
      overridesByTarget: {},
      storedTornadoDriverKeys: ['parameter:zero'],
      storedRowDriverKey: 'parameter:zero',
      storedColumnDriverKey: 'parameter:zero',
      maxDrivers: 12,
    }),
    {
      tornadoDriverKeys: ['parameter:one', 'parameter:two'],
      rowDriverKey: 'parameter:one',
      columnDriverKey: 'parameter:two',
    },
  );

  assert.deepEqual(
    resolveSensitivitySelections({
      assumptions,
      overridesByTarget: {},
      storedTornadoDriverKeys: [],
      storedRowDriverKey: 'parameter:one',
      storedColumnDriverKey: 'parameter:two',
      maxDrivers: 12,
    }).tornadoDriverKeys,
    ['parameter:one', 'parameter:two'],
  );

  assert.deepEqual(
    resolveSensitivitySelections({
      assumptions,
      overridesByTarget: { 'parameter:zero': '3' },
      storedTornadoDriverKeys: ['parameter:zero'],
      storedRowDriverKey: 'parameter:zero',
      storedColumnDriverKey: 'parameter:two',
      maxDrivers: 12,
    }),
    {
      tornadoDriverKeys: ['parameter:zero'],
      rowDriverKey: 'parameter:zero',
      columnDriverKey: 'parameter:two',
    },
  );
});

test('interactive driver selection retains one deterministic eligible non-zero target', () => {
  const assumptions = [
    numericAssumption('zero', '0'),
    numericAssumption('one', '1'),
    numericAssumption('two', '2'),
  ];
  assert.deepEqual(
    retainEligibleSensitivityDrivers(
      assumptions,
      {},
      ['parameter:zero'],
    ),
    ['parameter:one'],
  );
  assert.deepEqual(
    retainEligibleSensitivityDrivers(
      assumptions,
      { 'parameter:zero': '3' },
      [],
    ),
    ['parameter:zero'],
  );
  assert.deepEqual(
    retainEligibleSensitivityDrivers(
      [numericAssumption('zero', '0')],
      {},
      ['parameter:zero'],
    ),
    [],
  );
});

test('versioned sensitivity workbench round-trips only for the matching model and graph', () => {
  const storage = new MemoryStorage();
  const driverKey =
    'parameter:11111111-1111-4111-8111-111111111111';
  const document = {
    version: SENSITIVITY_WORKBENCH_VERSION,
    revision: 'revision-1',
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    comparisonBaselineRunId: 'baseline-run',
    currentRunId: 'current-run',
    analysisId: 'analysis-id',
    analysisOverridesByTarget: { [driverKey]: '10' },
    overridesByTarget: { [driverKey]: '12.5' },
    tornadoDriverKeys: [driverKey],
    selectedOutputId: 'output-id',
    rowDriverKey: driverKey,
    columnDriverKey: null,
  };

  storage.setItem(
    CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
    JSON.stringify(document),
  );
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
    JSON.stringify(document),
  );
});

test('corrupt workbench state is ignored while mutation failures remain observable', async () => {
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
    '{bad json',
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
  await assert.rejects(
    () =>
    clearCalculationArtifacts(throwingStorage, immediateLockManager),
    /blocked/,
  );
  await assert.rejects(
    () =>
      persistUploadIdentity(
        throwingStorage,
        uploadResponse(),
        immediateLockManager,
      ),
    /blocked/,
  );
  await assert.rejects(
    () =>
      persistGraphVersionId(
        throwingStorage,
        'graph-version',
        readPersistedCalculationState(throwingStorage),
        immediateLockManager,
      ),
    /blocked/,
  );
  await assert.rejects(
    () =>
      persistCalculationRunId(
        throwingStorage,
        'baseline',
        'baseline-run',
        readPersistedCalculationState(throwingStorage),
        immediateLockManager,
      ),
    /blocked/,
  );
  assert.equal(
    readSensitivityWorkbenchDocument(
      throwingStorage,
      'model-version',
      'graph-version',
    ),
    null,
  );

  const ignoredWrites: StorageLike = {
    getItem() {
      return null;
    },
    removeItem() {},
    setItem() {},
  };
  await assert.rejects(
    () =>
      persistCalculationRunId(
        ignoredWrites,
        'baseline',
        'baseline-run',
        readPersistedCalculationState(ignoredWrites),
        immediateLockManager,
      ),
    /did not persist/,
  );
});

test('workbench restore rejects non-finite decimal overrides and accepts signed scientific decimals', () => {
  const targetKey =
    'parameter:11111111-1111-4111-8111-111111111111';
  const validDocument = {
    version: SENSITIVITY_WORKBENCH_VERSION,
    revision: 'revision-1',
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    comparisonBaselineRunId: 'baseline-run',
    currentRunId: 'current-run',
    overridesByTarget: { [targetKey]: '-2.5e-3' },
    tornadoDriverKeys: [targetKey],
    selectedOutputId: null,
    rowDriverKey: null,
    columnDriverKey: null,
  };

  const validStorage = new MemoryStorage();
  validStorage.setItem(
    CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
    JSON.stringify(validDocument),
  );
  assert.deepEqual(
    readSensitivityWorkbenchDocument(
      validStorage,
      'model-version',
      'graph-version',
    ),
    validDocument,
  );

  for (const invalidValue of [
    '',
    ' ',
    'NaN',
    'Infinity',
    '-Infinity',
    '0x10',
  ]) {
    const storage = new MemoryStorage();
    storage.setItem(
      CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
      JSON.stringify({
        ...validDocument,
        overridesByTarget: { [targetKey]: invalidValue },
      }),
    );

    assert.equal(
      readSensitivityWorkbenchDocument(
        storage,
        'model-version',
        'graph-version',
      ),
      null,
      `expected ${JSON.stringify(invalidValue)} to be rejected`,
    );
    assert.equal(
      storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
      JSON.stringify({
        ...validDocument,
        overridesByTarget: { [targetKey]: invalidValue },
      }),
    );
  }
});

test('artifact clearing and graph changes remove the sensitivity workbench document', async () => {
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
  await clearCalculationArtifacts(storage, immediateLockManager);
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );

  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'old-graph');
  storeDocument();
  const expectedGraphIdentity = readPersistedCalculationState(storage);
  await persistGraphVersionId(
    storage,
    'new-graph',
    expectedGraphIdentity,
    immediateLockManager,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});

test('guarded sensitivity storage rejects cross-tab identity changes but accepts its own run update', () => {
  const storage = new MemoryStorage();
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'graph-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'baseline-run');
  storage.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'old-run');
  const expected = readPersistedCalculationState(storage);
  const guarded = createGuardedSensitivityStorage(storage, expected);

  assert.equal(matchesPersistedSensitivityIdentity(storage, expected), true);
  guarded.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'new-run');
  guarded.setItem(
    CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
    '{"selection":"new-run"}',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'new-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    '{"selection":"new-run"}',
  );
  assert.equal(guarded.matchesCurrent(), true);

  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'other-model');
  assert.equal(guarded.matchesCurrent(), false);
  guarded.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'stale-write');
  guarded.removeItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench);
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'new-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    '{"selection":"new-run"}',
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
    immediateLockManager,
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

test('GET-only sensitivity restore rethrows synthetic or unrelated 404s and retains override state', async () => {
  for (const detail of [
    {
      code: 'HTTP_404',
      message: 'proxy not found',
      retryable: false,
      resource_id: 'missing-override',
    },
    {
      code: 'CALCULATION_RUN_NOT_FOUND',
      message: 'different run missing',
      retryable: false,
      resource_id: 'different-run',
    },
  ]) {
    const storage = new MemoryStorage();
    storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'baseline-run');
    storage.setItem(
      CALCULATION_STORAGE_KEYS.overrideRunId,
      'missing-override',
    );
    const calls: string[] = [];
    const error = Object.assign(new Error(detail.message), {
      status: 404,
      detail,
    });

    await assert.rejects(
      () =>
        restoreSensitivityOutputProjection(
          storage,
          readPersistedCalculationState(storage),
          async (runId) => {
            calls.push(runId);
            throw error;
          },
          immediateLockManager,
        ),
      (caught) => caught === error,
    );
    assert.deepEqual(calls, ['missing-override']);
    assert.equal(
      storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
      'missing-override',
    );
    assert.equal(
      storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
      'baseline-run',
    );
  }
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

test('transient refresh may retain only the matching active model and graph identity', () => {
  const persisted = {
    workbookVersionId: null,
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    baselineRunId: 'baseline-run',
    overrideRunId: null,
  };
  assert.equal(
    canRetainSensitivityIdentity(
      {
        modelVersionId: 'model-version',
        graphVersionId: 'graph-version',
      },
      persisted,
    ),
    true,
  );
  assert.equal(
    canRetainSensitivityIdentity(
      {
        modelVersionId: 'other-model',
        graphVersionId: 'graph-version',
      },
      persisted,
    ),
    false,
  );
  assert.equal(canRetainSensitivityIdentity(null, persisted), false);
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
            output: projectedNumber('1000'),
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
      impact: row.impact,
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
        impact: 50,
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
        impact: null,
        low: null,
        current: 100,
        high: 1000,
        lowDelta: null,
        highDelta: 900,
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

test('sensitivity workbench composes canonical APIs and dynamic components without legacy mappings', () => {
  const pageSource = readFileSync('src/app/sensitivity/page.tsx', 'utf8');
  const componentSources = [
    'FixedSensitivityDashboard.tsx',
    'SensitivityAssumptionPanel.tsx',
    'SensitivityTornadoChart.tsx',
    'SensitivityTwoWayMatrix.tsx',
  ].map((fileName) => {
    try {
      return readFileSync(`src/components/sensitivity/${fileName}`, 'utf8');
    } catch {
      return '';
    }
  });
  const allSource = [pageSource, ...componentSources].join('\n');

  for (const requiredSource of [
    'FixedSensitivityDashboard',
    'getCalculationReadiness',
    'getCalculationRunOutputs',
    'runCalculation',
    'runCalculationSensitivity',
    'loadAllEditableNumericParameters',
    'restoreSensitivityOutputProjection',
    'comparison_baseline_run_id',
    'selectedOutputId',
    'tornadoDriverKeys',
    'resolveFixedDashboardViewModel',
    'estimateSensitivityKpis',
    'getCalculationSensitivityAnalysis',
    'promoteFixedDashboardDriver',
    'MAX_TORNADO_DRIVERS = 12',
  ]) {
    assert.ok(
      pageSource.includes(requiredSource),
      `expected sensitivity page to include ${requiredSource}`,
    );
  }
  assert.ok(allSource.includes('Reset all'), 'reset-all control must exist');
  assert.ok(allSource.includes('IRR tornado chart'));
  assert.ok(allSource.includes('Threshold unavailable'));
  assert.doesNotMatch(allSource, /<select/);
  assert.doesNotMatch(allSource, /Canonical time-series outputs/);

  for (const forbiddenSource of [
    'getModel',
    'parsed_json',
    'sheet_name',
    'cell_address',
    'baseIrr',
    'interp(',
    'LNG',
    'throughput',
    '12.3',
  ]) {
    assert.equal(
      allSource.includes(forbiddenSource),
      false,
      `sensitivity workbench must not include ${forbiddenSource}`,
    );
  }
  assert.doesNotMatch(allSource, /scenarios\/.*sensitivity/);
  assert.doesNotMatch(allSource, /new\s+(Map|Set)\s*\(\s*\[[\s\S]*IRR/i);
});

test('sensitivity bootstrap restores analysis by GET while exact and batch submissions stay separate', () => {
  const pageSource = readFileSync('src/app/sensitivity/page.tsx', 'utf8');
  const bootstrapStart = pageSource.indexOf('async function bootstrapWorkbench');
  const schedulerStart = pageSource.indexOf(
    'function scheduleExactCalculation',
  );

  assert.ok(bootstrapStart >= 0, 'bootstrap function must be explicit');
  assert.ok(
    schedulerStart > bootstrapStart,
    'user scheduler must remain separate from bootstrap',
  );
  const bootstrapSource = pageSource.slice(bootstrapStart, schedulerStart);
  assert.match(bootstrapSource, /getCalculationReadiness/);
  assert.match(bootstrapSource, /loadAllEditableNumericParameters/);
  assert.match(bootstrapSource, /restoreSensitivityOutputProjection/);
  assert.match(bootstrapSource, /const bootstrapStorage/);
  assert.match(
    bootstrapSource,
    /createGuardedSensitivityStorage\([\s\S]*bootstrapRevision === bootstrapRevisionRef\.current/,
  );
  assert.match(
    bootstrapSource,
    /restoreSensitivityOutputProjection\(\s*bootstrapStorage,/,
  );
  assert.match(
    bootstrapSource,
    /readSensitivityWorkbenchDocument\(\s*bootstrapStorage,/,
  );
  assert.match(bootstrapSource, /getCalculationSensitivityAnalysis/);
  assert.match(
    bootstrapSource,
    /catch \(caught\)[\s\S]*activeIdentityRef\.current = null;[\s\S]*return 'failed'/,
  );
  assert.match(
    bootstrapSource,
    /loadAllEditableNumericParameters\([\s\S]*identity\.graphVersionId/,
  );
  assert.doesNotMatch(bootstrapSource, /runCalculationSensitivity/);
  assert.doesNotMatch(bootstrapSource, /runCalculation\(/);
  assert.doesNotMatch(bootstrapSource, /method:\s*['"]POST['"]/);

  const exactPostIndex = pageSource.indexOf(
    'const calculation = await runCalculation(',
  );
  const outputGetIndex = pageSource.indexOf(
    'getCalculationRunOutputs(currentRunId)',
    exactPostIndex,
  );
  const outputIdentityIndex = pageSource.indexOf(
    'outputs.calculation_run_id !== currentRunId',
    outputGetIndex,
  );
  const exactPersistenceIndex = pageSource.indexOf(
    'persistSensitivityWorkbenchState(',
    outputIdentityIndex,
  );
  assert.ok(exactPostIndex >= 0, 'exact current POST must exist');
  assert.ok(outputGetIndex > exactPostIndex);
  assert.ok(outputIdentityIndex > outputGetIndex);
  assert.ok(exactPersistenceIndex > outputIdentityIndex);

  const postIndex = pageSource.indexOf('await runCalculationSensitivity(');
  const responseGuardIndex = pageSource.indexOf(
    'canApplySensitivityResponse(',
    postIndex,
  );
  const persistenceIndex = pageSource.indexOf(
    'persistSensitivityWorkbenchState(',
    responseGuardIndex,
  );
  const appliedStateIndex = pageSource.indexOf(
    'setWorkbench(() => appliedWorkbench)',
    persistenceIndex,
  );

  assert.ok(postIndex >= 0, 'analysis POST must exist');
  assert.ok(responseGuardIndex > postIndex, 'POST response must be guarded');
  assert.ok(
    persistenceIndex > responseGuardIndex,
    'artifact storage must follow the guarded analysis response',
  );
  assert.ok(
    appliedStateIndex > persistenceIndex,
    'successful server results must become visible only after storage commits',
  );
  assert.match(pageSource, /workbenchDocumentRevisionRef\.current/);
  assert.match(
    pageSource,
    /activeIdentityRef\.current = null;[\s\S]*Could not load the sensitivity workbench/,
  );
  assert.match(pageSource, /expectedDocumentRevision/);
  assert.match(pageSource, /window\.addEventListener\('storage'/);
  assert.match(pageSource, /void bootstrapWorkbench\(\)/);
  assert.match(pageSource, /SENSITIVITY_DEBOUNCE_MS\s*=\s*400/);
  assert.match(pageSource, /requestRevisionRef\.current/);
  assert.match(pageSource, /clearTimeout/);
  assert.match(pageSource, /matchesCurrent\(\)/);
  assert.match(pageSource, /current_run_id = currentRunId/);
  assert.match(pageSource, /pendingExactCalculationRef/);
  assert.match(pageSource, /exactCalculationInFlightRef/);
  assert.match(pageSource, /analysisOverridesByTarget/);
  assert.match(
    pageSource,
    /buildCanonicalOverrideCalculationRequest\([\s\S]*requestWorkbench\.overridesByTarget/,
  );
});

test('sensitivity review fixes expose retained-state, zero-driver, provenance, and accessible chart affordances', () => {
  const pageSource = readFileSync('src/app/sensitivity/page.tsx', 'utf8');
  const navSource = readFileSync('src/app/NavBar.tsx', 'utf8');
  const panelSource = readFileSync(
    'src/components/sensitivity/SensitivityAssumptionPanel.tsx',
    'utf8',
  );
  const fixedSource = readFileSync(
    'src/components/sensitivity/FixedSensitivityDashboard.tsx',
    'utf8',
  );
  const tornadoSource = readFileSync(
    'src/components/sensitivity/SensitivityTornadoChart.tsx',
    'utf8',
  );
  const matrixSource = readFileSync(
    'src/components/sensitivity/SensitivityTwoWayMatrix.tsx',
    'utf8',
  );

  assert.match(pageSource, /resolveFixedDashboardViewModel/);
  assert.match(pageSource, /orderFixedDashboardAssumptions/);
  assert.match(pageSource, /promoteFixedDashboardDriver/);
  assert.match(pageSource, /rowDriverKey: null/);
  assert.match(pageSource, /columnDriverKey: null/);
  assert.match(pageSource, /SENSITIVITY_DEBOUNCE_MS = 400/);
  assert.match(
    pageSource,
    /dashboard\.irrOutputId === null[\s\S]*KPI cards still recalculate/,
  );
  assert.doesNotMatch(pageSource, /Canonical time-series outputs/);
  assert.doesNotMatch(fixedSource, /<select/);
  assert.match(fixedSource, /Decision Confidence/);
  assert.match(fixedSource, /Threshold unavailable/);
  assert.match(fixedSource, /Live Model KPIs/);
  assert.match(fixedSource, /Assumption sliders/);
  assert.match(fixedSource, /IRR tornado chart/);
  assert.match(fixedSource, /Scenario comparison/);
  assert.match(fixedSource, /Two-way sensitivity/);
  assert.match(fixedSource, /Current Assumptions/);
  assert.match(fixedSource, /sm:grid-cols-2 xl:grid-cols-5/);
  assert.match(fixedSource, /overflow-x-auto/);
  assert.match(fixedSource, /focus-visible:ring-2/);
  assert.equal(
    navSource.match(
      /bg-d-bg text-white border-t border-d-border overflow-x-auto/g,
    )?.length,
    2,
  );
  assert.match(
    navSource,
    /ROW 1: Brand \+ Project pill[\s\S]*<div className="bg-d-card text-white overflow-x-auto">/,
  );
  assert.match(panelSource, /useMemo/);
  assert.doesNotMatch(panelSource, /tornado driver/i);
  assert.doesNotMatch(panelSource, /type="checkbox"/);
  assert.match(
    panelSource,
    /const baseSpec = deriveSliderSpec\(assumption\.currentValue\)/,
  );
  assert.match(
    panelSource,
    /baseSpec\.kind === 'number'[\s\S]*deriveSliderSpec\(value\)[\s\S]*: baseSpec/,
  );
  assert.match(tornadoSource, /Case provenance/);
  assert.match(tornadoSource, /formatDelta/);
  assert.doesNotMatch(matrixSource, /normalized \* 0\.64/);
});

test('application root contains narrow-screen overflow while sensitivity regions remain independently scrollable', () => {
  const layoutSource = readFileSync('src/app/layout.tsx', 'utf8');
  const navSource = readFileSync('src/app/NavBar.tsx', 'utf8');
  const tornadoSource = readFileSync(
    'src/components/sensitivity/SensitivityTornadoChart.tsx',
    'utf8',
  );
  const matrixSource = readFileSync(
    'src/components/sensitivity/SensitivityTwoWayMatrix.tsx',
    'utf8',
  );

  assert.match(
    layoutSource,
    /<html[^>]*className="[^"]*\boverflow-x-hidden\b[^"]*"[^>]*>/,
  );
  assert.match(
    layoutSource,
    /<div className="[^"]*\boverflow-x-hidden\b[^"]*">[\s\S]*<NavBar \/>[\s\S]*<main/,
  );
  assert.equal(navSource.match(/\boverflow-x-auto\b/g)?.length, 3);
  assert.match(tornadoSource, /\boverflow-x-auto\b/);
  assert.match(matrixSource, /\boverflow-x-auto\b/);
});

test('only the newest sensitivity response may apply when requests resolve out of order', async () => {
  const applied: string[] = [];
  let currentRevision = 0;

  const settle = async (
    response: CalculationSensitivityResponse,
    revision: number,
    delay: number,
  ) => {
    await new Promise((resolve) => setTimeout(resolve, delay));
    if (
      canApplySensitivityResponse(response, {
        requestRevision: revision,
        currentRevision,
        modelVersionId: 'model-version',
        graphVersionId: 'graph-version',
        outputId: 'project-irr-output',
      })
    ) {
      applied.push(response.current_run_id);
    }
  };

  currentRevision = 1;
  const older = settle(
    sensitivityResponse({ current_run_id: 'older-run' }),
    1,
    10,
  );
  currentRevision = 2;
  const newer = settle(
    sensitivityResponse({ current_run_id: 'newer-run' }),
    2,
    0,
  );

  await Promise.all([older, newer]);
  assert.deepEqual(applied, ['newer-run']);
});
