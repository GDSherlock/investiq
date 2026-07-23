import type {
  CalculationSensitivityResponse,
  CalculationRunResponse,
  WorkbookValidationResponse,
} from './calculation-api-types';
import { canStartCalculationFlow } from './calculation-flow';

export interface StorageLike {
  getItem(key: string): string | null;
  removeItem(key: string): void;
  setItem(key: string, value: string): void;
}

export const CALCULATION_STORAGE_KEYS = {
  workbookVersionId: 'investiq_workbook_version_id',
  modelVersionId: 'investiq_model_version_id',
  graphVersionId: 'investiq_calculation_graph_version_id',
  baselineRunId: 'investiq_baseline_calculation_run_id',
  overrideRunId: 'investiq_override_calculation_run_id',
  sensitivityWorkbench: 'investiq_sensitivity_workbench:v2',
} as const;

const LEGACY_SENSITIVITY_WORKBENCH_KEY =
  'investiq_sensitivity_workbench:v1';

export const SENSITIVITY_WORKBENCH_VERSION = 2 as const;

export interface SensitivityWorkbenchDocument {
  version: 2;
  revision: string;
  modelVersionId: string;
  graphVersionId: string;
  comparisonBaselineRunId: string;
  currentRunId: string;
  overridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  selectedOutputId: string | null;
  rowDriverKey: string | null;
  columnDriverKey: string | null;
}

export type SensitivityWorkbenchDraft = Omit<
  SensitivityWorkbenchDocument,
  | 'version'
  | 'revision'
  | 'comparisonBaselineRunId'
  | 'currentRunId'
>;

type SensitivityRunSelection = Pick<
  CalculationSensitivityResponse,
  | 'model_version_id'
  | 'graph_version_id'
  | 'comparison_baseline_run_id'
  | 'current_run_id'
>;

export type SensitivityWorkbenchPersistenceResult =
  | { status: 'persisted'; revision: string }
  | { status: 'superseded' }
  | {
      status: 'conflict';
      reason: 'identity' | 'document_revision';
    }
  | {
      status: 'unavailable';
      reason:
        | 'read_failed'
        | 'write_failed'
        | 'rollback_failed'
        | 'verification_failed'
        | 'invalid_document'
        | 'lock_unavailable'
        | 'lock_failed';
      storageState: 'unchanged' | 'restored' | 'unknown';
    };

export interface SensitivityWorkbenchLockManager {
  request<T>(
    name: string,
    options: { mode: 'exclusive' },
    callback: () => T | PromiseLike<T>,
  ): Promise<T>;
}

export interface PersistSensitivityWorkbenchStateInput {
  expectedIdentity: PersistedSensitivityIdentity;
  expectedDocumentRevision: string | null;
  nextDocumentRevision: string;
  response: SensitivityRunSelection;
  document: SensitivityWorkbenchDraft;
  isCurrent?: () => boolean;
}

export interface PersistedCalculationState {
  workbookVersionId: string | null;
  modelVersionId: string | null;
  graphVersionId: string | null;
  baselineRunId: string | null;
  overrideRunId: string | null;
}

export type PersistedSensitivityIdentity = Pick<
  PersistedCalculationState,
  | 'modelVersionId'
  | 'graphVersionId'
  | 'baselineRunId'
  | 'overrideRunId'
>;

export interface GuardedSensitivityStorage extends StorageLike {
  matchesCurrent(): boolean;
}

export interface RestorableCalculationIdentity {
  modelVersionId: string;
  workbookVersionId: string;
}

const CANONICAL_TARGET_KEY_PATTERN =
  /^(parameter|financial_series_value):[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function safeGetItem(storage: StorageLike, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function safeRemoveItem(storage: StorageLike, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // Storage may be unavailable or disabled.
  }
}

function safeSetItem(storage: StorageLike, key: string, value: string): void {
  try {
    storage.setItem(key, value);
  } catch {
    // Storage may be unavailable, disabled, or full.
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCanonicalTargetKey(value: unknown): value is string {
  return (
    typeof value === 'string' && CANONICAL_TARGET_KEY_PATTERN.test(value)
  );
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isDocumentRevision(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 128 &&
    /^[A-Za-z0-9._:-]+$/.test(value)
  );
}

function isFiniteDecimalString(value: unknown): value is string {
  if (typeof value !== 'string') {
    return false;
  }
  const normalized = value.trim();
  return (
    normalized.length > 0 &&
    /^[+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?$/.test(normalized) &&
    Number.isFinite(Number(normalized))
  );
}

function isSensitivityWorkbenchDocument(
  value: unknown,
): value is SensitivityWorkbenchDocument {
  if (
    !isRecord(value) ||
    value.version !== SENSITIVITY_WORKBENCH_VERSION ||
    !isDocumentRevision(value.revision) ||
    typeof value.modelVersionId !== 'string' ||
    typeof value.graphVersionId !== 'string' ||
    typeof value.comparisonBaselineRunId !== 'string' ||
    typeof value.currentRunId !== 'string' ||
    !isRecord(value.overridesByTarget) ||
    !Array.isArray(value.tornadoDriverKeys) ||
    !isNullableString(value.selectedOutputId) ||
    !isNullableString(value.rowDriverKey) ||
    !isNullableString(value.columnDriverKey)
  ) {
    return false;
  }
  if (
    !Object.entries(value.overridesByTarget).every(
      ([key, decimalValue]) =>
        isCanonicalTargetKey(key) &&
        isFiniteDecimalString(decimalValue),
    ) ||
    !value.tornadoDriverKeys.every(isCanonicalTargetKey) ||
    (value.rowDriverKey !== null &&
      !isCanonicalTargetKey(value.rowDriverKey)) ||
    (value.columnDriverKey !== null &&
      !isCanonicalTargetKey(value.columnDriverKey))
  ) {
    return false;
  }
  return true;
}

function normalizeStoredIdentity(value: string | null): string | null {
  const normalized = value?.trim();
  if (
    !normalized ||
    normalized.toLowerCase() === 'undefined' ||
    normalized.toLowerCase() === 'null'
  ) {
    return null;
  }
  return normalized;
}

function clearSensitivityWorkbenchDocuments(
  storage: StorageLike,
): void {
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.sensitivityWorkbench);
  safeRemoveItem(storage, LEGACY_SENSITIVITY_WORKBENCH_KEY);
}

function clearCalculationArtifactsUnlocked(storage: StorageLike): void {
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.graphVersionId);
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.baselineRunId);
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.overrideRunId);
  clearSensitivityWorkbenchDocuments(storage);
}

export async function clearCalculationArtifacts(
  storage: StorageLike,
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<void> {
  await withCalculationStorageLock(
    () => clearCalculationArtifactsUnlocked(storage),
    lockManager,
  );
}

export async function persistUploadIdentity(
  storage: StorageLike,
  response: WorkbookValidationResponse,
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<boolean> {
  if (!canStartCalculationFlow(response)) {
    return false;
  }
  return withCalculationStorageLock(
    () => {
      const previousModelVersionId = safeGetItem(
        storage,
        CALCULATION_STORAGE_KEYS.modelVersionId,
      );
      if (
        previousModelVersionId !== null &&
        previousModelVersionId !== response.model_version_id
      ) {
        clearCalculationArtifactsUnlocked(storage);
      }
      safeSetItem(
        storage,
        CALCULATION_STORAGE_KEYS.workbookVersionId,
        response.workbook_version_id,
      );
      safeSetItem(
        storage,
        CALCULATION_STORAGE_KEYS.modelVersionId,
        response.model_version_id,
      );
      return true;
    },
    lockManager,
  );
}

export async function persistGraphVersionId(
  storage: StorageLike,
  graphVersionId: string,
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<void> {
  await withCalculationStorageLock(
    () => {
      const previousGraphVersionId = safeGetItem(
        storage,
        CALCULATION_STORAGE_KEYS.graphVersionId,
      );
      if (
        previousGraphVersionId !== null &&
        previousGraphVersionId !== graphVersionId
      ) {
        safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.baselineRunId);
        safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.overrideRunId);
        clearSensitivityWorkbenchDocuments(storage);
      }
      safeSetItem(
        storage,
        CALCULATION_STORAGE_KEYS.graphVersionId,
        graphVersionId,
      );
    },
    lockManager,
  );
}

export async function persistCalculationRunId(
  storage: StorageLike,
  kind: 'baseline' | 'override',
  runId: string,
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<void> {
  await withCalculationStorageLock(
    () => {
      const key =
        kind === 'baseline'
          ? CALCULATION_STORAGE_KEYS.baselineRunId
          : CALCULATION_STORAGE_KEYS.overrideRunId;
      const runSelectionChanged =
        safeGetItem(storage, key) !== runId ||
        (kind === 'baseline' &&
          safeGetItem(
            storage,
            CALCULATION_STORAGE_KEYS.overrideRunId,
          ) !== null);
      if (runSelectionChanged) {
        clearSensitivityWorkbenchDocuments(storage);
      }
      if (kind === 'baseline') {
        safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.overrideRunId);
      }
      safeSetItem(storage, key, runId);
    },
    lockManager,
  );
}

export async function removePersistedCalculationRunId(
  storage: StorageLike,
  kind: 'baseline' | 'override',
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<void> {
  await withCalculationStorageLock(
    () => {
      safeRemoveItem(
        storage,
        kind === 'baseline'
          ? CALCULATION_STORAGE_KEYS.baselineRunId
          : CALCULATION_STORAGE_KEYS.overrideRunId,
      );
      if (kind === 'baseline') {
        safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.overrideRunId);
      }
      clearSensitivityWorkbenchDocuments(storage);
    },
    lockManager,
  );
}

export function readPersistedCalculationState(
  storage: StorageLike,
): PersistedCalculationState {
  return {
    workbookVersionId: safeGetItem(
      storage,
      CALCULATION_STORAGE_KEYS.workbookVersionId,
    ),
    modelVersionId: safeGetItem(
      storage,
      CALCULATION_STORAGE_KEYS.modelVersionId,
    ),
    graphVersionId: safeGetItem(
      storage,
      CALCULATION_STORAGE_KEYS.graphVersionId,
    ),
    baselineRunId: safeGetItem(
      storage,
      CALCULATION_STORAGE_KEYS.baselineRunId,
    ),
    overrideRunId: safeGetItem(
      storage,
      CALCULATION_STORAGE_KEYS.overrideRunId,
    ),
  };
}

export function matchesPersistedSensitivityIdentity(
  storage: StorageLike,
  expected: PersistedSensitivityIdentity,
): boolean {
  const current = readPersistedCalculationState(storage);
  return (
    current.modelVersionId === expected.modelVersionId &&
    current.graphVersionId === expected.graphVersionId &&
    current.baselineRunId === expected.baselineRunId &&
    current.overrideRunId === expected.overrideRunId
  );
}

export function createGuardedSensitivityStorage(
  storage: StorageLike,
  initialExpected: PersistedSensitivityIdentity,
  contextIsCurrent: () => boolean = () => true,
): GuardedSensitivityStorage {
  const expected = { ...initialExpected };
  const matchesCurrent = () =>
    contextIsCurrent() &&
    matchesPersistedSensitivityIdentity(storage, expected);

  const updateExpectedRunSelection = (
    key: string,
    value: string | null,
  ) => {
    if (key === CALCULATION_STORAGE_KEYS.baselineRunId) {
      expected.baselineRunId = value;
    } else if (key === CALCULATION_STORAGE_KEYS.overrideRunId) {
      expected.overrideRunId = value;
    }
  };

  return {
    matchesCurrent,
    getItem(key: string) {
      if (!matchesCurrent()) {
        return null;
      }
      return safeGetItem(storage, key);
    },
    removeItem(key: string) {
      if (!matchesCurrent()) {
        return;
      }
      try {
        storage.removeItem(key);
        updateExpectedRunSelection(key, null);
      } catch {
        // Storage may be unavailable or disabled.
      }
    },
    setItem(key: string, value: string) {
      if (!matchesCurrent()) {
        return;
      }
      try {
        storage.setItem(key, value);
        updateExpectedRunSelection(key, value);
      } catch {
        // Storage may be unavailable, disabled, or full.
      }
    },
  };
}

export function readSensitivityWorkbenchDocument(
  storage: StorageLike,
  modelVersionId: string,
  graphVersionId: string,
  comparisonBaselineRunId?: string,
  currentRunId?: string,
): SensitivityWorkbenchDocument | null {
  const rawDocument = safeGetItem(
    storage,
    CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
  );
  if (rawDocument === null) {
    return null;
  }

  let parsedDocument: unknown;
  try {
    parsedDocument = JSON.parse(rawDocument);
  } catch {
    return null;
  }
  if (
    !isSensitivityWorkbenchDocument(parsedDocument) ||
    parsedDocument.modelVersionId !== modelVersionId ||
    parsedDocument.graphVersionId !== graphVersionId ||
    (comparisonBaselineRunId !== undefined &&
      parsedDocument.comparisonBaselineRunId !==
        comparisonBaselineRunId) ||
    (currentRunId !== undefined &&
      parsedDocument.currentRunId !== currentRunId)
  ) {
    return null;
  }
  return parsedDocument;
}

interface SensitivityStorageSnapshot {
  baselineRunId: string | null;
  overrideRunId: string | null;
  document: string | null;
}

function restoreRawStorageItem(
  storage: StorageLike,
  key: string,
  value: string | null,
): boolean {
  try {
    if (value === null) {
      storage.removeItem(key);
    } else {
      storage.setItem(key, value);
    }
    return true;
  } catch {
    return false;
  }
}

function restoreSensitivityStorageSnapshot(
  storage: StorageLike,
  snapshot: SensitivityStorageSnapshot,
): boolean {
  const writesSucceeded = [
    restoreRawStorageItem(
      storage,
      CALCULATION_STORAGE_KEYS.baselineRunId,
      snapshot.baselineRunId,
    ),
    restoreRawStorageItem(
      storage,
      CALCULATION_STORAGE_KEYS.overrideRunId,
      snapshot.overrideRunId,
    ),
    restoreRawStorageItem(
      storage,
      CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
      snapshot.document,
    ),
  ].every(Boolean);
  try {
    return (
      writesSucceeded &&
      storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId) ===
        snapshot.baselineRunId &&
      storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId) ===
        snapshot.overrideRunId &&
      storage.getItem(
        CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
      ) === snapshot.document
    );
  } catch {
    return false;
  }
}

function parseSensitivityWorkbenchDocument(
  rawDocument: string | null,
): SensitivityWorkbenchDocument | null {
  if (rawDocument === null) {
    return null;
  }
  try {
    const parsedDocument: unknown = JSON.parse(rawDocument);
    return isSensitivityWorkbenchDocument(parsedDocument)
      ? parsedDocument
      : null;
  } catch {
    return null;
  }
}

function persistSensitivityWorkbenchStateUnderLock(
  storage: StorageLike,
  input: PersistSensitivityWorkbenchStateInput,
): SensitivityWorkbenchPersistenceResult {
  const {
    expectedIdentity,
    expectedDocumentRevision,
    nextDocumentRevision,
    response,
    document,
    isCurrent,
  } = input;
  if (isCurrent?.() === false) {
    return { status: 'superseded' };
  }
  if (
    !isDocumentRevision(nextDocumentRevision) ||
    document.modelVersionId !== response.model_version_id ||
    document.graphVersionId !== response.graph_version_id
  ) {
    return {
      status: 'unavailable',
      reason: 'invalid_document',
      storageState: 'unchanged',
    };
  }
  if (
    expectedIdentity.modelVersionId !== response.model_version_id ||
    expectedIdentity.graphVersionId !== response.graph_version_id ||
    expectedIdentity.baselineRunId !==
      response.comparison_baseline_run_id
  ) {
    return { status: 'conflict', reason: 'identity' };
  }

  let previousBaselineRunId: string | null;
  let previousOverrideRunId: string | null;
  let previousDocument: string | null;
  let currentModelVersionId: string | null;
  let currentGraphVersionId: string | null;
  try {
    currentModelVersionId = storage.getItem(
      CALCULATION_STORAGE_KEYS.modelVersionId,
    );
    currentGraphVersionId = storage.getItem(
      CALCULATION_STORAGE_KEYS.graphVersionId,
    );
    previousBaselineRunId = storage.getItem(
      CALCULATION_STORAGE_KEYS.baselineRunId,
    );
    previousOverrideRunId = storage.getItem(
      CALCULATION_STORAGE_KEYS.overrideRunId,
    );
    previousDocument = storage.getItem(
      CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
    );
  } catch {
    return {
      status: 'unavailable',
      reason: 'read_failed',
      storageState: 'unchanged',
    };
  }

  if (isCurrent?.() === false) {
    return { status: 'superseded' };
  }
  if (
    currentModelVersionId !== expectedIdentity.modelVersionId ||
    currentGraphVersionId !== expectedIdentity.graphVersionId ||
    previousBaselineRunId !== expectedIdentity.baselineRunId ||
    previousOverrideRunId !== expectedIdentity.overrideRunId
  ) {
    return { status: 'conflict', reason: 'identity' };
  }

  const currentDocument =
    parseSensitivityWorkbenchDocument(previousDocument);
  if (
    (currentDocument !== null &&
      (currentDocument.modelVersionId !== document.modelVersionId ||
        currentDocument.graphVersionId !== document.graphVersionId ||
        currentDocument.comparisonBaselineRunId !==
          previousBaselineRunId ||
        currentDocument.currentRunId !==
          (previousOverrideRunId ?? previousBaselineRunId))) ||
    (currentDocument?.revision ?? null) !== expectedDocumentRevision
  ) {
    return { status: 'conflict', reason: 'document_revision' };
  }

  const nextDocument: SensitivityWorkbenchDocument = {
    ...document,
    version: SENSITIVITY_WORKBENCH_VERSION,
    revision: nextDocumentRevision,
    comparisonBaselineRunId:
      response.comparison_baseline_run_id,
    currentRunId: response.current_run_id,
  };
  if (!isSensitivityWorkbenchDocument(nextDocument)) {
    return {
      status: 'unavailable',
      reason: 'invalid_document',
      storageState: 'unchanged',
    };
  }
  const serializedDocument = JSON.stringify(nextDocument);
  const nextOverrideRunId =
    response.current_run_id ===
    response.comparison_baseline_run_id
      ? null
      : response.current_run_id;

  const snapshot: SensitivityStorageSnapshot = {
    baselineRunId: previousBaselineRunId,
    overrideRunId: previousOverrideRunId,
    document: previousDocument,
  };
  try {
    storage.setItem(
      CALCULATION_STORAGE_KEYS.baselineRunId,
      response.comparison_baseline_run_id,
    );
    if (nextOverrideRunId === null) {
      storage.removeItem(CALCULATION_STORAGE_KEYS.overrideRunId);
    } else {
      storage.setItem(
        CALCULATION_STORAGE_KEYS.overrideRunId,
        nextOverrideRunId,
      );
    }
    storage.setItem(
      CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
      serializedDocument,
    );
    storage.removeItem(LEGACY_SENSITIVITY_WORKBENCH_KEY);
  } catch {
    const restored = restoreSensitivityStorageSnapshot(
      storage,
      snapshot,
    );
    return restored
      ? {
          status: 'unavailable',
          reason: 'write_failed',
          storageState: 'restored',
        }
      : {
          status: 'unavailable',
          reason: 'rollback_failed',
          storageState: 'unknown',
        };
  }

  try {
    if (
      storage.getItem(CALCULATION_STORAGE_KEYS.baselineRunId) !==
        response.comparison_baseline_run_id ||
      storage.getItem(CALCULATION_STORAGE_KEYS.overrideRunId) !==
        nextOverrideRunId ||
      storage.getItem(CALCULATION_STORAGE_KEYS.sensitivityWorkbench) !==
        serializedDocument
    ) {
      const restored = restoreSensitivityStorageSnapshot(
        storage,
        snapshot,
      );
      return restored
        ? {
            status: 'unavailable',
            reason: 'verification_failed',
            storageState: 'restored',
          }
        : {
            status: 'unavailable',
            reason: 'rollback_failed',
            storageState: 'unknown',
          };
    }
  } catch {
    const restored = restoreSensitivityStorageSnapshot(
      storage,
      snapshot,
    );
    return restored
      ? {
          status: 'unavailable',
          reason: 'read_failed',
          storageState: 'restored',
        }
      : {
          status: 'unavailable',
          reason: 'rollback_failed',
          storageState: 'unknown',
        };
  }

  return { status: 'persisted', revision: nextDocumentRevision };
}

function browserSensitivityLockManager():
  | SensitivityWorkbenchLockManager
  | null {
  const candidate = (
    globalThis as {
      navigator?: { locks?: SensitivityWorkbenchLockManager };
    }
  ).navigator?.locks;
  return candidate?.request ? candidate : null;
}

function resolveCalculationStorageLockManager(
  lockManager?: SensitivityWorkbenchLockManager | null,
): SensitivityWorkbenchLockManager | null {
  return lockManager === undefined
    ? browserSensitivityLockManager()
    : lockManager;
}

export function isCalculationStorageLockAvailable(
  lockManager?: SensitivityWorkbenchLockManager | null,
): boolean {
  return resolveCalculationStorageLockManager(lockManager) !== null;
}

const CALCULATION_STORAGE_LOCK_NAME =
  'investiq-calculation-storage-persistence';

export async function withCalculationStorageLock<T>(
  callback: () => T | PromiseLike<T>,
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<T> {
  const resolvedLockManager =
    resolveCalculationStorageLockManager(lockManager);
  if (resolvedLockManager === null) {
    throw new Error(
      'This browser does not provide the exclusive storage lock required for calculation persistence.',
    );
  }
  return resolvedLockManager.request(
    CALCULATION_STORAGE_LOCK_NAME,
    { mode: 'exclusive' },
    callback,
  );
}

export async function persistSensitivityWorkbenchState(
  storage: StorageLike,
  input: PersistSensitivityWorkbenchStateInput,
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<SensitivityWorkbenchPersistenceResult> {
  if (input.isCurrent?.() === false) {
    return { status: 'superseded' };
  }
  const resolvedLockManager =
    resolveCalculationStorageLockManager(lockManager);
  if (resolvedLockManager === null) {
    return {
      status: 'unavailable',
      reason: 'lock_unavailable',
      storageState: 'unchanged',
    };
  }
  try {
    return await resolvedLockManager.request(
      CALCULATION_STORAGE_LOCK_NAME,
      { mode: 'exclusive' },
      () => persistSensitivityWorkbenchStateUnderLock(storage, input),
    );
  } catch {
    return {
      status: 'unavailable',
      reason: 'lock_failed',
      storageState: 'unchanged',
    };
  }
}

export function readRestorableCalculationIdentity(
  storage: StorageLike,
): RestorableCalculationIdentity | null {
  const persisted = readPersistedCalculationState(storage);
  const modelVersionId = normalizeStoredIdentity(persisted.modelVersionId);
  const workbookVersionId = normalizeStoredIdentity(
    persisted.workbookVersionId,
  );
  if (!modelVersionId || !workbookVersionId) {
    return null;
  }
  return { modelVersionId, workbookVersionId };
}

export function shouldAutoRunBaseline(
  state: PersistedCalculationState,
): boolean {
  return state.baselineRunId === null && state.overrideRunId === null;
}

export async function reconcileStoredRun(
  storage: StorageLike,
  kind: 'baseline' | 'override',
  run: CalculationRunResponse,
  modelVersionId: string,
  graphVersionId: string,
  lockManager?: SensitivityWorkbenchLockManager | null,
): Promise<{ isCurrent: boolean; notice: string | null }> {
  const isCurrent =
    run.model_version_id === modelVersionId &&
    run.graph_version_id === graphVersionId;
  if (isCurrent) {
    return { isCurrent: true, notice: null };
  }

  await removePersistedCalculationRunId(
    storage,
    kind,
    lockManager,
  );
  return {
    isCurrent: false,
    notice: `Stored ${kind} run belongs to a different model or graph and was cleared.`,
  };
}
