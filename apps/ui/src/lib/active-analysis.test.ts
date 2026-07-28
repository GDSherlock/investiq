import assert from 'node:assert/strict';
import test from 'node:test';

import {
  hydrateActiveAnalysis,
  resolveActiveAnalysis,
} from './active-analysis';
import {
  CALCULATION_STORAGE_KEYS,
  type PersistedCalculationState,
  type StorageLike,
} from './calculation-storage';
import type {
  CalculationReadinessResponse,
  CalculationRunResponse,
} from './calculation-api-types';

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

function storeState(
  storage: StorageLike,
  value: PersistedCalculationState,
): void {
  for (const [field, key] of Object.entries(
    CALCULATION_STORAGE_KEYS,
  )) {
    if (field === 'sensitivityWorkbench') {
      continue;
    }
    const storedValue = value[field as keyof PersistedCalculationState];
    if (storedValue !== null) {
      storage.setItem(key, storedValue);
    }
  }
}

function readiness(
  overrides: Partial<CalculationReadinessResponse> = {},
): CalculationReadinessResponse {
  return {
    model_version_id: 'model-version',
    workbook_version_id: 'workbook-version',
    model_status: 'ready',
    validation_status: 'valid',
    status: 'ready',
    calculation_rule_extraction_id: 'extraction-id',
    graph_version_id: 'graph-version',
    versions: {
      phase1_ir: '1',
      phase2_ir: '1',
      compiler: '1',
      engine: '1',
      registry: '1',
      semantics: '1',
    },
    summary: {
      formula_cells_total: 1,
      formula_cells_supported: 1,
      graph_nodes: 1,
      graph_edges: 0,
    },
    warnings: [],
    error: null,
    ...overrides,
  };
}

function run(
  overrides: Partial<CalculationRunResponse> = {},
): CalculationRunResponse {
  return {
    calculation_run_id: 'baseline-run',
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

const lockManager = {
  request: async <T>(
    _name: string,
    _options: { mode: 'exclusive' },
    callback: () => T | PromiseLike<T>,
  ): Promise<T> => callback(),
};

function state(
  overrides: Partial<PersistedCalculationState> = {},
): PersistedCalculationState {
  return {
    workbookVersionId: 'workbook-version',
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    baselineRunId: 'baseline-run',
    overrideRunId: null,
    ...overrides,
  };
}

test('active analysis prioritizes the selected override run', () => {
  assert.deepEqual(
    resolveActiveAnalysis(state({ overrideRunId: 'override-run' })),
    {
      status: 'ready',
      modelVersionId: 'model-version',
      graphVersionId: 'graph-version',
      baselineRunId: 'baseline-run',
      activeRunId: 'override-run',
      activeRunKind: 'override',
    },
  );
});

test('active analysis falls back to baseline without an override', () => {
  assert.equal(resolveActiveAnalysis(state()).activeRunId, 'baseline-run');
  assert.equal(resolveActiveAnalysis(state()).activeRunKind, 'baseline');
});

test('active analysis never starts a calculation when no run is persisted', () => {
  assert.deepEqual(
    resolveActiveAnalysis(
      state({ baselineRunId: null, overrideRunId: null }),
    ),
    {
      status: 'needs_calculation',
      modelVersionId: 'model-version',
      graphVersionId: 'graph-version',
      baselineRunId: null,
      activeRunId: null,
      activeRunKind: null,
    },
  );
});

test('active analysis distinguishes empty and not-yet-prepared identities', () => {
  assert.equal(
    resolveActiveAnalysis(
      state({
        modelVersionId: null,
        graphVersionId: null,
        baselineRunId: null,
      }),
    ).status,
    'empty',
  );
  assert.equal(
    resolveActiveAnalysis(
      state({
        graphVersionId: null,
        baselineRunId: null,
      }),
    ).status,
    'needs_readiness',
  );
});

test('hydration reads readiness and stores its graph without starting a run', async () => {
  const storage = new MemoryStorage();
  storeState(
    storage,
    state({
      graphVersionId: null,
      baselineRunId: null,
      overrideRunId: null,
    }),
  );
  const readinessRequests: string[] = [];
  const runRequests: string[] = [];

  const result = await hydrateActiveAnalysis(storage, {
    getReadiness: async (modelVersionId) => {
      readinessRequests.push(modelVersionId);
      return readiness();
    },
    getRun: async (runId) => {
      runRequests.push(runId);
      return run();
    },
    lockManager,
  });

  assert.equal(result.status, 'needs_calculation');
  assert.equal(result.graphVersionId, 'graph-version');
  assert.deepEqual(readinessRequests, ['model-version']);
  assert.deepEqual(runRequests, []);
});

test('hydration validates the selected override run identity', async () => {
  const storage = new MemoryStorage();
  storeState(storage, state({ overrideRunId: 'override-run' }));
  const runRequests: string[] = [];

  const result = await hydrateActiveAnalysis(storage, {
    getReadiness: async () => readiness(),
    getRun: async (runId) => {
      runRequests.push(runId);
      return run({ calculation_run_id: 'override-run' });
    },
  });

  assert.equal(result.activeRunId, 'override-run');
  assert.deepEqual(runRequests, ['override-run']);
});

test('hydration rejects a persisted run from a different calculation identity', async () => {
  const storage = new MemoryStorage();
  storeState(storage, state());

  await assert.rejects(
    hydrateActiveAnalysis(storage, {
      getReadiness: async () => readiness(),
      getRun: async () => run({ graph_version_id: 'other-graph' }),
    }),
    /does not match the active model and graph/,
  );
});
