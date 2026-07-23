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
  sensitivityWorkbench: 'investiq_sensitivity_workbench:v1',
} as const;

export const SENSITIVITY_WORKBENCH_VERSION = 1 as const;

export interface SensitivityWorkbenchDocument {
  version: 1;
  modelVersionId: string;
  graphVersionId: string;
  overridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  selectedOutputId: string | null;
  rowDriverKey: string | null;
  columnDriverKey: string | null;
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
    typeof value.modelVersionId !== 'string' ||
    typeof value.graphVersionId !== 'string' ||
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

export function clearCalculationArtifacts(storage: StorageLike): void {
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.graphVersionId);
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.baselineRunId);
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.overrideRunId);
  safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.sensitivityWorkbench);
}

export function persistUploadIdentity(
  storage: StorageLike,
  response: WorkbookValidationResponse,
): boolean {
  if (!canStartCalculationFlow(response)) {
    return false;
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
}

export function persistGraphVersionId(
  storage: StorageLike,
  graphVersionId: string,
): void {
  const previousGraphVersionId = safeGetItem(
    storage,
    CALCULATION_STORAGE_KEYS.graphVersionId,
  );
  if (
    previousGraphVersionId !== null &&
    previousGraphVersionId !== graphVersionId
  ) {
    safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.sensitivityWorkbench);
  }
  safeSetItem(
    storage,
    CALCULATION_STORAGE_KEYS.graphVersionId,
    graphVersionId,
  );
}

export function persistCalculationRunId(
  storage: StorageLike,
  kind: 'baseline' | 'override',
  runId: string,
): void {
  safeSetItem(
    storage,
    kind === 'baseline'
      ? CALCULATION_STORAGE_KEYS.baselineRunId
      : CALCULATION_STORAGE_KEYS.overrideRunId,
    runId,
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

export function persistSensitivityWorkbenchDocument(
  storage: StorageLike,
  document: SensitivityWorkbenchDocument,
): void {
  try {
    safeSetItem(
      storage,
      CALCULATION_STORAGE_KEYS.sensitivityWorkbench,
      JSON.stringify(document),
    );
  } catch {
    // The minimal document is expected to be serializable.
  }
}

export function readSensitivityWorkbenchDocument(
  storage: StorageLike,
  modelVersionId: string,
  graphVersionId: string,
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
    safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.sensitivityWorkbench);
    return null;
  }
  if (
    !isSensitivityWorkbenchDocument(parsedDocument) ||
    parsedDocument.modelVersionId !== modelVersionId ||
    parsedDocument.graphVersionId !== graphVersionId
  ) {
    safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.sensitivityWorkbench);
    return null;
  }
  return parsedDocument;
}

export function persistSensitivityRunSelection(
  storage: StorageLike,
  response: CalculationSensitivityResponse,
): void {
  safeSetItem(
    storage,
    CALCULATION_STORAGE_KEYS.baselineRunId,
    response.comparison_baseline_run_id,
  );
  if (response.current_run_id === response.comparison_baseline_run_id) {
    safeRemoveItem(storage, CALCULATION_STORAGE_KEYS.overrideRunId);
    return;
  }
  safeSetItem(
    storage,
    CALCULATION_STORAGE_KEYS.overrideRunId,
    response.current_run_id,
  );
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

export function reconcileStoredRun(
  storage: StorageLike,
  kind: 'baseline' | 'override',
  run: CalculationRunResponse,
  modelVersionId: string,
  graphVersionId: string,
): { isCurrent: boolean; notice: string | null } {
  const isCurrent =
    run.model_version_id === modelVersionId &&
    run.graph_version_id === graphVersionId;
  if (isCurrent) {
    return { isCurrent: true, notice: null };
  }

  safeRemoveItem(
    storage,
    kind === 'baseline'
      ? CALCULATION_STORAGE_KEYS.baselineRunId
      : CALCULATION_STORAGE_KEYS.overrideRunId,
  );
  return {
    isCurrent: false,
    notice: `Stored ${kind} run belongs to a different model or graph and was cleared.`,
  };
}
