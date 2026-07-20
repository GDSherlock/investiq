import type {
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
} as const;

export interface PersistedCalculationState {
  workbookVersionId: string | null;
  modelVersionId: string | null;
  graphVersionId: string | null;
  baselineRunId: string | null;
  overrideRunId: string | null;
}

export function clearCalculationArtifacts(storage: StorageLike): void {
  storage.removeItem(CALCULATION_STORAGE_KEYS.graphVersionId);
  storage.removeItem(CALCULATION_STORAGE_KEYS.baselineRunId);
  storage.removeItem(CALCULATION_STORAGE_KEYS.overrideRunId);
}

export function persistUploadIdentity(
  storage: StorageLike,
  response: WorkbookValidationResponse,
): boolean {
  if (!canStartCalculationFlow(response)) {
    return false;
  }
  storage.setItem(
    CALCULATION_STORAGE_KEYS.workbookVersionId,
    response.workbook_version_id,
  );
  storage.setItem(
    CALCULATION_STORAGE_KEYS.modelVersionId,
    response.model_version_id,
  );
  return true;
}

export function persistGraphVersionId(
  storage: StorageLike,
  graphVersionId: string,
): void {
  storage.setItem(CALCULATION_STORAGE_KEYS.graphVersionId, graphVersionId);
}

export function persistCalculationRunId(
  storage: StorageLike,
  kind: 'baseline' | 'override',
  runId: string,
): void {
  storage.setItem(
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
    workbookVersionId: storage.getItem(
      CALCULATION_STORAGE_KEYS.workbookVersionId,
    ),
    modelVersionId: storage.getItem(
      CALCULATION_STORAGE_KEYS.modelVersionId,
    ),
    graphVersionId: storage.getItem(
      CALCULATION_STORAGE_KEYS.graphVersionId,
    ),
    baselineRunId: storage.getItem(
      CALCULATION_STORAGE_KEYS.baselineRunId,
    ),
    overrideRunId: storage.getItem(
      CALCULATION_STORAGE_KEYS.overrideRunId,
    ),
  };
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

  storage.removeItem(
    kind === 'baseline'
      ? CALCULATION_STORAGE_KEYS.baselineRunId
      : CALCULATION_STORAGE_KEYS.overrideRunId,
  );
  return {
    isCurrent: false,
    notice: `Stored ${kind} run belongs to a different model or graph and was cleared.`,
  };
}
