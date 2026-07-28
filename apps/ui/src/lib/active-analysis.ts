import type {
  CalculationReadinessResponse,
  CalculationRunResponse,
} from './calculation-api-types';
import {
  persistGraphVersionId,
  readPersistedCalculationState,
  type PersistedCalculationState,
  type SensitivityWorkbenchLockManager,
  type StorageLike,
} from './calculation-storage';

export type ActiveAnalysisStatus =
  | 'empty'
  | 'needs_readiness'
  | 'needs_calculation'
  | 'ready';

export interface ActiveAnalysisResolution {
  status: ActiveAnalysisStatus;
  modelVersionId: string | null;
  graphVersionId: string | null;
  baselineRunId: string | null;
  activeRunId: string | null;
  activeRunKind: 'baseline' | 'override' | null;
}

export interface ActiveAnalysisReadDependencies {
  getReadiness(
    modelVersionId: string,
  ): Promise<CalculationReadinessResponse>;
  getRun(calculationRunId: string): Promise<CalculationRunResponse>;
  lockManager?: SensitivityWorkbenchLockManager | null;
}

export function resolveActiveAnalysis(
  state: PersistedCalculationState,
): ActiveAnalysisResolution {
  if (state.modelVersionId === null) {
    return {
      status: 'empty',
      modelVersionId: null,
      graphVersionId: null,
      baselineRunId: null,
      activeRunId: null,
      activeRunKind: null,
    };
  }
  if (state.graphVersionId === null) {
    return {
      status: 'needs_readiness',
      modelVersionId: state.modelVersionId,
      graphVersionId: null,
      baselineRunId: null,
      activeRunId: null,
      activeRunKind: null,
    };
  }
  const activeRunId = state.overrideRunId ?? state.baselineRunId;
  const activeRunKind =
    state.overrideRunId !== null
      ? 'override'
      : state.baselineRunId !== null
        ? 'baseline'
        : null;
  return {
    status: activeRunId === null ? 'needs_calculation' : 'ready',
    modelVersionId: state.modelVersionId,
    graphVersionId: state.graphVersionId,
    baselineRunId: state.baselineRunId,
    activeRunId,
    activeRunKind,
  };
}

export async function hydrateActiveAnalysis(
  storage: StorageLike,
  dependencies: ActiveAnalysisReadDependencies,
): Promise<ActiveAnalysisResolution> {
  let persisted = readPersistedCalculationState(storage);
  let resolution = resolveActiveAnalysis(persisted);

  if (
    resolution.status === 'needs_readiness' &&
    resolution.modelVersionId !== null
  ) {
    const readiness = await dependencies.getReadiness(
      resolution.modelVersionId,
    );
    if (readiness.model_version_id !== resolution.modelVersionId) {
      throw new Error(
        'Calculation readiness belongs to a different model.',
      );
    }
    if (
      ['ready', 'ready_with_warning'].includes(readiness.status) &&
      readiness.graph_version_id !== null
    ) {
      await persistGraphVersionId(
        storage,
        readiness.graph_version_id,
        persisted,
        dependencies.lockManager,
      );
      persisted = readPersistedCalculationState(storage);
      resolution = resolveActiveAnalysis(persisted);
    }
  }

  if (
    resolution.status === 'ready' &&
    resolution.activeRunId !== null
  ) {
    const run = await dependencies.getRun(resolution.activeRunId);
    if (
      run.calculation_run_id !== resolution.activeRunId ||
      run.model_version_id !== resolution.modelVersionId ||
      run.graph_version_id !== resolution.graphVersionId
    ) {
      throw new Error(
        'Persisted calculation run does not match the active model and graph.',
      );
    }
    if (!['completed', 'completed_with_warning'].includes(run.status)) {
      throw new Error(
        `Persisted calculation run is not available (${run.status}).`,
      );
    }
  }

  return resolution;
}
