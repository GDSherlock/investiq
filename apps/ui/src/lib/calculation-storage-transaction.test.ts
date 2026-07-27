import assert from 'node:assert/strict';
import test from 'node:test';

import type { CalculationSensitivityResponse } from './calculation-api-types';
import {
  CALCULATION_STORAGE_KEYS,
  SENSITIVITY_WORKBENCH_VERSION,
  persistCalculationRunId,
  persistGraphVersionId,
  persistSensitivityWorkbenchState,
  readPersistedCalculationState,
  readSensitivityWorkbenchDocument,
  removePersistedCalculationRunId,
  type SensitivityWorkbenchLockManager,
  type SensitivityWorkbenchDraft,
  type StorageLike,
} from './calculation-storage';

class MemoryStorage implements StorageLike {
  protected readonly values = new Map<string, string>();

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

class OneShotDocumentFailureStorage extends MemoryStorage {
  private shouldFail = true;

  override setItem(key: string, value: string): void {
    if (
      this.shouldFail &&
      key === CALCULATION_STORAGE_KEYS.sensitivityWorkbench
    ) {
      this.shouldFail = false;
      throw new Error('quota exceeded');
    }
    super.setItem(key, value);
  }
}

class IrrecoverableDocumentFailureStorage extends MemoryStorage {
  private armed = false;

  arm(): void {
    this.armed = true;
  }

  override setItem(key: string, value: string): void {
    if (
      this.armed &&
      key === CALCULATION_STORAGE_KEYS.sensitivityWorkbench
    ) {
      throw new Error('quota exceeded');
    }
    if (
      this.armed &&
      key === CALCULATION_STORAGE_KEYS.overrideRunId &&
      value === 'old-run'
    ) {
      throw new Error('rollback blocked');
    }
    super.setItem(key, value);
  }
}

class SerialLockManager implements SensitivityWorkbenchLockManager {
  private tail = Promise.resolve();
  private active = 0;
  maxActive = 0;

  request<T>(
    _name: string,
    _options: { mode: 'exclusive' },
    callback: () => T | PromiseLike<T>,
  ): Promise<T> {
    const run = this.tail.then(async () => {
      this.active += 1;
      this.maxActive = Math.max(this.maxActive, this.active);
      try {
        await Promise.resolve();
        return await callback();
      } finally {
        this.active -= 1;
      }
    });
    this.tail = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }
}

const DRIVER_KEY =
  'parameter:11111111-1111-4111-8111-111111111111';

function seedCalculationIdentity(storage: StorageLike): void {
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'graph-version');
  storage.setItem(CALCULATION_STORAGE_KEYS.baselineRunId, 'baseline-run');
  storage.setItem(CALCULATION_STORAGE_KEYS.overrideRunId, 'old-run');
}

function analysis(
  currentRunId = 'current-run',
): Pick<
  CalculationSensitivityResponse,
  | 'model_version_id'
  | 'graph_version_id'
  | 'comparison_baseline_run_id'
  | 'current_run_id'
> {
  return {
    model_version_id: 'model-version',
    graph_version_id: 'graph-version',
    comparison_baseline_run_id: 'baseline-run',
    current_run_id: currentRunId,
  };
}

function draft(value: string): SensitivityWorkbenchDraft {
  return {
    modelVersionId: 'model-version',
    graphVersionId: 'graph-version',
    overridesByTarget: { [DRIVER_KEY]: value },
    tornadoDriverKeys: [DRIVER_KEY],
    analysisTornadoDriverKeys: [DRIVER_KEY],
    selectedOutputId: 'output-id',
    rowDriverKey: DRIVER_KEY,
    columnDriverKey: null,
  };
}

test('workbench compare-and-write commits run IDs and the revisioned document together', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);
  const expectedIdentity = readPersistedCalculationState(storage);

  const result = await persistSensitivityWorkbenchState(
    storage,
    {
      expectedIdentity,
      expectedDocumentRevision: null,
      nextDocumentRevision: 'revision-1',
      response: analysis(),
      document: draft('12.5'),
    },
    locks,
  );

  assert.deepEqual(result, {
    status: 'persisted',
    revision: 'revision-1',
  });
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
    'baseline-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'current-run',
  );
  assert.deepEqual(
    readSensitivityWorkbenchDocument(
      storage,
      'model-version',
      'graph-version',
      'baseline-run',
      'current-run',
    ),
    {
      version: SENSITIVITY_WORKBENCH_VERSION,
      revision: 'revision-1',
      comparisonBaselineRunId: 'baseline-run',
      currentRunId: 'current-run',
      ...draft('12.5'),
    },
  );
});

test('simultaneous same-run writers serialize and one stale revision conflicts', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);
  const initialIdentity = readPersistedCalculationState(storage);
  assert.equal(
    (
      await persistSensitivityWorkbenchState(
        storage,
        {
          expectedIdentity: initialIdentity,
          expectedDocumentRevision: null,
          nextDocumentRevision: 'revision-1',
          response: analysis(),
          document: draft('10'),
        },
        locks,
      )
    ).status,
    'persisted',
  );

  const sameRunIdentity = readPersistedCalculationState(storage);
  const firstWriter = persistSensitivityWorkbenchState(
    storage,
    {
      expectedIdentity: sameRunIdentity,
      expectedDocumentRevision: 'revision-1',
      nextDocumentRevision: 'revision-2',
      response: analysis(),
      document: draft('20'),
    },
    locks,
  );
  const staleWriter = persistSensitivityWorkbenchState(
    storage,
    {
      expectedIdentity: sameRunIdentity,
      expectedDocumentRevision: 'revision-1',
      nextDocumentRevision: 'stale-revision',
      response: analysis(),
      document: draft('99'),
    },
    locks,
  );
  const [firstResult, staleResult] = await Promise.all([
    firstWriter,
    staleWriter,
  ]);
  assert.deepEqual(firstResult, {
    status: 'persisted',
    revision: 'revision-2',
  });
  assert.deepEqual(staleResult, {
    status: 'conflict',
    reason: 'document_revision',
  });
  assert.equal(locks.maxActive, 1);
  assert.equal(
    readSensitivityWorkbenchDocument(
      storage,
      'model-version',
      'graph-version',
      'baseline-run',
      'current-run',
    )?.overridesByTarget[DRIVER_KEY],
    '20',
  );
});

test('calculation-page run writers share the lock and the latest queued selection wins', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);
  const initialIdentity = readPersistedCalculationState(storage);
  assert.equal(
    (
      await persistSensitivityWorkbenchState(
        storage,
        {
          expectedIdentity: initialIdentity,
          expectedDocumentRevision: null,
          nextDocumentRevision: 'revision-1',
          response: analysis(),
          document: draft('10'),
        },
        locks,
      )
    ).status,
    'persisted',
  );

  const currentIdentity = readPersistedCalculationState(storage);
  const sensitivityWriter = persistSensitivityWorkbenchState(
    storage,
    {
      expectedIdentity: currentIdentity,
      expectedDocumentRevision: 'revision-1',
      nextDocumentRevision: 'revision-2',
      response: analysis(),
      document: draft('20'),
    },
    locks,
  );
  const calculationPageWriter = persistCalculationRunId(
    storage,
    'override',
    'calculation-page-run',
    currentIdentity,
    locks,
  );

  const [sensitivityResult, calculationResult] = await Promise.all([
    sensitivityWriter,
    calculationPageWriter,
  ]);
  assert.deepEqual(sensitivityResult, {
    status: 'persisted',
    revision: 'revision-2',
  });
  assert.equal(calculationResult, true);
  assert.equal(locks.maxActive, 1);
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'calculation-page-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});

test('reselecting the same baseline clears the override and its sensitivity document', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);
  assert.equal(
    (
      await persistSensitivityWorkbenchState(
        storage,
        {
          expectedIdentity: readPersistedCalculationState(storage),
          expectedDocumentRevision: null,
          nextDocumentRevision: 'revision-1',
          response: analysis(),
          document: draft('10'),
        },
        locks,
      )
    ).status,
    'persisted',
  );

  const expectedIdentity = readPersistedCalculationState(storage);
  await persistCalculationRunId(
    storage,
    'baseline',
    'baseline-run',
    expectedIdentity,
    locks,
  );

  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
    'baseline-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    null,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});

test('delayed graph and run writers reject a cross-tab model switch', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'workbook-a',
  );
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-a');
  const delayedGraphIdentity = readPersistedCalculationState(storage);

  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'workbook-b',
  );
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-b');

  assert.equal(
    await persistGraphVersionId(
      storage,
      'graph-a',
      delayedGraphIdentity,
      locks,
    ),
    false,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.modelVersionId),
    'model-b',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.graphVersionId),
    null,
  );

  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'workbook-a',
  );
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-a');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'graph-a');
  storage.setItem(
    CALCULATION_STORAGE_KEYS.baselineRunId,
    'baseline-a',
  );
  const delayedRunIdentity = readPersistedCalculationState(storage);

  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'workbook-b',
  );
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-b');
  storage.removeItem(CALCULATION_STORAGE_KEYS.graphVersionId);
  storage.removeItem(CALCULATION_STORAGE_KEYS.baselineRunId);

  assert.equal(
    await persistCalculationRunId(
      storage,
      'override',
      'run-a',
      delayedRunIdentity,
      locks,
    ),
    false,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    null,
  );
});

test('late baseline cannot erase a newer run selection for the same model and graph', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);
  const sharedExpectedIdentity =
    readPersistedCalculationState(storage);

  assert.equal(
    await persistCalculationRunId(
      storage,
      'override',
      'newer-override',
      sharedExpectedIdentity,
      locks,
    ),
    true,
  );
  assert.equal(
    await persistCalculationRunId(
      storage,
      'baseline',
      'late-baseline',
      sharedExpectedIdentity,
      locks,
    ),
    false,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
    'baseline-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'newer-override',
  );
});

test('late readiness cannot replace a newer graph for the same model', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'workbook-a',
  );
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-a');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'graph-0');
  const sharedExpectedIdentity =
    readPersistedCalculationState(storage);

  assert.equal(
    await persistGraphVersionId(
      storage,
      'graph-new',
      sharedExpectedIdentity,
      locks,
    ),
    true,
  );
  assert.equal(
    await persistGraphVersionId(
      storage,
      'graph-late',
      sharedExpectedIdentity,
      locks,
    ),
    false,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.graphVersionId),
    'graph-new',
  );
});

test('late missing-run cleanup cannot erase a newer model selection', async () => {
  const storage = new MemoryStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);
  const delayedCleanupIdentity =
    readPersistedCalculationState(storage);

  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    'workbook-b',
  );
  storage.setItem(CALCULATION_STORAGE_KEYS.modelVersionId, 'model-b');
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, 'graph-b');
  storage.setItem(
    CALCULATION_STORAGE_KEYS.baselineRunId,
    'baseline-b',
  );
  storage.setItem(
    CALCULATION_STORAGE_KEYS.overrideRunId,
    'override-b',
  );

  assert.equal(
    await removePersistedCalculationRunId(
      storage,
      'baseline',
      delayedCleanupIdentity,
      locks,
    ),
    false,
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
    'baseline-b',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'override-b',
  );
});

test('storage write failures are observable and restore the previous run selection', async () => {
  const storage = new OneShotDocumentFailureStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);

  const result = await persistSensitivityWorkbenchState(
    storage,
    {
      expectedIdentity: readPersistedCalculationState(storage),
      expectedDocumentRevision: null,
      nextDocumentRevision: 'revision-1',
      response: analysis(),
      document: draft('12.5'),
    },
    locks,
  );

  assert.deepEqual(result, {
    status: 'unavailable',
    reason: 'write_failed',
    storageState: 'restored',
  });
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId),
    'baseline-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'old-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});

test('irrecoverable rollback reports unknown storage state instead of claiming restoration', async () => {
  const storage = new IrrecoverableDocumentFailureStorage();
  const locks = new SerialLockManager();
  seedCalculationIdentity(storage);
  storage.arm();

  const result = await persistSensitivityWorkbenchState(
    storage,
    {
      expectedIdentity: readPersistedCalculationState(storage),
      expectedDocumentRevision: null,
      nextDocumentRevision: 'revision-1',
      response: analysis(),
      document: draft('12.5'),
    },
    locks,
  );

  assert.deepEqual(result, {
    status: 'unavailable',
    reason: 'rollback_failed',
    storageState: 'unknown',
  });
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'current-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});

test('missing locks and superseded requests leave storage unchanged', async () => {
  const storage = new MemoryStorage();
  seedCalculationIdentity(storage);
  const input = {
    expectedIdentity: readPersistedCalculationState(storage),
    expectedDocumentRevision: null,
    nextDocumentRevision: 'revision-1',
    response: analysis(),
    document: draft('12.5'),
  };

  assert.deepEqual(
    await persistSensitivityWorkbenchState(storage, input, null),
    {
      status: 'unavailable',
      reason: 'lock_unavailable',
      storageState: 'unchanged',
    },
  );
  assert.deepEqual(
    await persistSensitivityWorkbenchState(
      storage,
      { ...input, isCurrent: () => false },
      new SerialLockManager(),
    ),
    { status: 'superseded' },
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId),
    'old-run',
  );
  assert.equal(
    storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench),
    null,
  );
});
