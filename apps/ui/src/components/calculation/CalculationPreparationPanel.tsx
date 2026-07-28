'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  getCalculationReadiness,
  getCalculationRun,
  prepareCalculation,
  runCalculation,
} from '@/lib/api';
import type {
  CalculationReadinessResponse,
  CalculationRunResponse,
  CalculationUiPhase,
  WorkbookValidationResponse,
} from '@/lib/calculation-api-types';
import {
  buildBaselineRequest,
  isCalculationReady,
} from '@/lib/calculation-flow';
import {
  persistCalculationRunId,
  persistGraphVersionId,
  readPersistedCalculationState,
  reconcileStoredRun,
  removePersistedCalculationRunId,
  shouldAutoRunBaseline,
} from '@/lib/calculation-storage';
import {
  buildPreparationNotifications,
  buildTechnicalDetails,
} from '@/lib/model-preparation-view';

import { CalculationRunSummary } from './CalculationRunSummary';
import { PreparationNotifications } from './PreparationNotifications';

export type CalculationPreparationLifecycle =
  | 'processing'
  | 'completed'
  | 'failed';

interface CalculationPreparationPanelProps {
  modelVersionId: string;
  workbookVersionId: string;
  restoreFromStorage: boolean;
  uploadResult: WorkbookValidationResponse | null;
  onLifecycleChange?: (
    lifecycle: CalculationPreparationLifecycle,
  ) => void;
}

function isCompletedRun(run: CalculationRunResponse): boolean {
  return (
    run.status === 'completed' || run.status === 'completed_with_warning'
  );
}

function phaseLabel(
  phase: CalculationUiPhase,
  readiness: CalculationReadinessResponse | null,
): string {
  switch (phase) {
    case 'checking_readiness':
      return 'Checking readiness';
    case 'not_prepared':
      return 'Preparation required';
    case 'preparing':
      return 'Preparing';
    case 'running_baseline':
      return 'Creating baseline';
    case 'ready_for_override':
      return 'Preparation ready';
    case 'completed':
      return readiness?.status === 'ready_with_warning'
        ? 'Completed with warnings'
        : 'Completed';
    case 'failed':
      return 'Failed';
    default:
      return 'Processing';
  }
}

export function CalculationPreparationPanel({
  modelVersionId,
  workbookVersionId,
  restoreFromStorage,
  uploadResult,
  onLifecycleChange,
}: CalculationPreparationPanelProps) {
  const [phase, setPhase] =
    useState<CalculationUiPhase>('checking_readiness');
  const [readiness, setReadiness] =
    useState<CalculationReadinessResponse | null>(null);
  const [graphVersionId, setGraphVersionId] = useState<string | null>(
    null,
  );
  const [baselineRun, setBaselineRun] =
    useState<CalculationRunResponse | null>(null);
  const [overrideRun, setOverrideRun] =
    useState<CalculationRunResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [stateNotice, setStateNotice] = useState<string | null>(null);
  const identityRevisionRef = useRef(0);
  const baselineInFlightRef = useRef(false);

  const notifyLifecycle = useCallback(
    (lifecycle: CalculationPreparationLifecycle) => {
      onLifecycleChange?.(lifecycle);
    },
    [onLifecycleChange],
  );

  const executeBaseline = useCallback(
    async (targetGraphVersionId: string, requestRevision: number) => {
      if (baselineInFlightRef.current) {
        return;
      }
      baselineInFlightRef.current = true;
      setPhase('running_baseline');
      setError(null);
      setStateNotice(null);
      notifyLifecycle('processing');
      try {
        const expectedIdentity = readPersistedCalculationState(
          window.localStorage,
        );
        if (
          expectedIdentity.workbookVersionId !== workbookVersionId ||
          expectedIdentity.modelVersionId !== modelVersionId ||
          expectedIdentity.graphVersionId !== targetGraphVersionId ||
          expectedIdentity.baselineRunId !== null ||
          expectedIdentity.overrideRunId !== null
        ) {
          throw new Error(
            'Stored calculation identity changed before the baseline request.',
          );
        }

        const run = await runCalculation(
          modelVersionId,
          buildBaselineRequest(targetGraphVersionId),
        );
        if (requestRevision !== identityRevisionRef.current) {
          return;
        }
        if (
          run.model_version_id !== modelVersionId ||
          run.graph_version_id !== targetGraphVersionId
        ) {
          throw new Error(
            'Baseline response belongs to a different model or graph.',
          );
        }
        if (!isCompletedRun(run)) {
          throw new Error(
            `Baseline calculation did not complete (${run.status}).`,
          );
        }

        const persisted = await persistCalculationRunId(
          window.localStorage,
          'baseline',
          run.calculation_run_id,
          expectedIdentity,
        );
        if (!persisted) {
          throw new Error(
            'Stored calculation identity changed while the baseline was running.',
          );
        }
        setBaselineRun(run);
        setOverrideRun(null);
        setPhase('completed');
        notifyLifecycle('completed');
      } catch (caught) {
        if (requestRevision === identityRevisionRef.current) {
          setError(
            caught instanceof Error
              ? caught
              : new Error('Baseline calculation failed.'),
          );
          setPhase('failed');
          notifyLifecycle('failed');
        }
      } finally {
        baselineInFlightRef.current = false;
      }
    },
    [
      modelVersionId,
      notifyLifecycle,
      workbookVersionId,
    ],
  );

  const restorePersistedRuns = useCallback(
    async (
      targetGraphVersionId: string,
      initialIdentity: ReturnType<typeof readPersistedCalculationState>,
      requestRevision: number,
    ) => {
      const expectedIdentity = initialIdentity;
      const requests: {
        kind: 'baseline' | 'override';
        runId: string;
      }[] = [];
      if (initialIdentity.baselineRunId) {
        requests.push({
          kind: 'baseline',
          runId: initialIdentity.baselineRunId,
        });
      }
      if (initialIdentity.overrideRunId) {
        requests.push({
          kind: 'override',
          runId: initialIdentity.overrideRunId,
        });
      }

      const settled = await Promise.allSettled(
        requests.map(({ runId }) => getCalculationRun(runId)),
      );
      if (requestRevision !== identityRevisionRef.current) {
        return;
      }

      let restoredBaseline: CalculationRunResponse | null = null;
      let restoredOverride: CalculationRunResponse | null = null;
      let firstError: Error | null = null;

      for (let index = 0; index < settled.length; index += 1) {
        const result = settled[index];
        const { kind, runId } = requests[index];
        if (result.status === 'rejected') {
          const caught =
            result.reason instanceof Error
              ? result.reason
              : new Error(`Could not reload the stored ${kind} run.`);
          const missing =
            'status' in caught &&
            (caught as Error & { status?: number }).status === 404;
          if (missing) {
            const removed = await removePersistedCalculationRunId(
              window.localStorage,
              kind,
              expectedIdentity,
            );
            if (!removed) {
              setError(
                new Error(
                  'Stored calculation identity changed while persisted runs were loading.',
                ),
              );
              setPhase('failed');
              notifyLifecycle('failed');
              return;
            }
            setStateNotice(
              `Stored ${kind} run ${runId} was not found and was cleared.`,
            );
          } else {
            firstError ??= caught;
          }
          continue;
        }

        if (!isCompletedRun(result.value)) {
          firstError ??= new Error(
            `Stored ${kind} run is not complete (${result.value.status}).`,
          );
          continue;
        }
        const reconciled = await reconcileStoredRun(
          window.localStorage,
          kind,
          result.value,
          modelVersionId,
          targetGraphVersionId,
          expectedIdentity,
        );
        if (!reconciled.isCurrent) {
          if (reconciled.disposition === 'conflict') {
            setStateNotice(reconciled.notice);
            setError(
              new Error(
                reconciled.notice ??
                  'Stored calculation identity changed while persisted runs were loading.',
              ),
            );
            setPhase('failed');
            notifyLifecycle('failed');
            return;
          }
          setStateNotice(reconciled.notice);
          continue;
        }
        if (kind === 'baseline') {
          restoredBaseline = result.value;
        } else {
          restoredOverride = result.value;
        }
      }

      if (restoredOverride && !restoredBaseline) {
        firstError ??= new Error(
          'Stored override run cannot be used without its baseline run.',
        );
        restoredOverride = null;
      }

      setBaselineRun(restoredBaseline);
      setOverrideRun(restoredOverride);
      setError(firstError);
      if (firstError) {
        setPhase('failed');
        notifyLifecycle('failed');
        return;
      }
      const restoredKinds = [
        restoredBaseline ? 'baseline' : null,
        restoredOverride ? 'override' : null,
      ].filter(Boolean);
      setStateNotice(
        restoredKinds.length > 0
          ? `Restored persisted ${restoredKinds.join(
              ' and ',
            )} run via GET; no calculation was submitted.`
          : 'No current persisted calculation run could be restored.',
      );
      setPhase(restoredBaseline ? 'completed' : 'ready_for_override');
      notifyLifecycle(restoredBaseline ? 'completed' : 'processing');
    },
    [modelVersionId, notifyLifecycle],
  );

  const activateReadyCalculation = useCallback(
    async (
      response: CalculationReadinessResponse,
      requestRevision: number,
      expectedIdentity: ReturnType<
        typeof readPersistedCalculationState
      >,
    ) => {
      const targetGraphVersionId = response.graph_version_id;
      if (!targetGraphVersionId) {
        setError(new Error('Ready response did not include graph_version_id.'));
        setPhase('failed');
        notifyLifecycle('failed');
        return;
      }

      const identityMatches =
        expectedIdentity.workbookVersionId === workbookVersionId &&
        expectedIdentity.modelVersionId === modelVersionId;
      const hadPersistedRuns =
        identityMatches &&
        (expectedIdentity.baselineRunId !== null ||
          expectedIdentity.overrideRunId !== null);
      const graphMatches =
        identityMatches &&
        (expectedIdentity.graphVersionId === null ||
          expectedIdentity.graphVersionId === targetGraphVersionId);

      if (!identityMatches) {
        throw new Error(
          'Stored calculation identity changed while readiness was loading.',
        );
      }
      const graphPersisted = await persistGraphVersionId(
        window.localStorage,
        targetGraphVersionId,
        expectedIdentity,
      );
      if (!graphPersisted) {
        throw new Error(
          'Stored calculation identity changed while readiness was loading.',
        );
      }
      setGraphVersionId(targetGraphVersionId);

      if (hadPersistedRuns && graphMatches) {
        await restorePersistedRuns(
          targetGraphVersionId,
          expectedIdentity,
          requestRevision,
        );
        return;
      }
      if (hadPersistedRuns && !graphMatches) {
        setStateNotice(
          'Stored calculation graph changed, so stale run IDs were cleared.',
        );
        setPhase('ready_for_override');
        notifyLifecycle('processing');
        return;
      }
      if (restoreFromStorage) {
        setStateNotice(
          'Restored calculation readiness from stored version IDs. No calculation was submitted.',
        );
        setPhase('ready_for_override');
        notifyLifecycle('processing');
        return;
      }
      if (shouldAutoRunBaseline(expectedIdentity)) {
        await executeBaseline(targetGraphVersionId, requestRevision);
        return;
      }
      setPhase('ready_for_override');
      notifyLifecycle('completed');
    },
    [
      executeBaseline,
      modelVersionId,
      notifyLifecycle,
      restoreFromStorage,
      restorePersistedRuns,
      workbookVersionId,
    ],
  );

  useEffect(() => {
    const requestRevision = ++identityRevisionRef.current;
    let cancelled = false;

    async function initialize() {
      setPhase('checking_readiness');
      setError(null);
      setStateNotice(null);
      notifyLifecycle('processing');
      try {
        const expectedIdentity = readPersistedCalculationState(
          window.localStorage,
        );
        const response = await getCalculationReadiness(modelVersionId);
        if (
          cancelled ||
          requestRevision !== identityRevisionRef.current
        ) {
          return;
        }
        if (
          response.model_version_id !== modelVersionId ||
          response.workbook_version_id !== workbookVersionId
        ) {
          throw new Error(
            'Readiness response belongs to a different model or workbook.',
          );
        }
        setReadiness(response);

        if (isCalculationReady(response.status)) {
          await activateReadyCalculation(
            response,
            requestRevision,
            expectedIdentity,
          );
          return;
        }
        if (response.status === 'preparing') {
          setPhase('preparing');
          notifyLifecycle('processing');
        } else if (response.status === 'not_prepared') {
          setPhase('not_prepared');
          notifyLifecycle('failed');
        } else if (response.status === 'model_not_ready') {
          setError(
            new Error(
              'The model has not been materialized. Calculation preparation is unavailable.',
            ),
          );
          setPhase('failed');
          notifyLifecycle('failed');
        } else {
          setPhase('failed');
          notifyLifecycle('failed');
        }
      } catch (caught) {
        if (
          !cancelled &&
          requestRevision === identityRevisionRef.current
        ) {
          setError(
            caught instanceof Error
              ? caught
              : new Error('Calculation readiness failed.'),
          );
          setPhase('failed');
          notifyLifecycle('failed');
        }
      }
    }

    void initialize();
    return () => {
      identityRevisionRef.current += 1;
      cancelled = true;
    };
  }, [
    activateReadyCalculation,
    modelVersionId,
    notifyLifecycle,
    workbookVersionId,
  ]);

  const handlePrepare = async () => {
    const requestRevision = identityRevisionRef.current;
    setPhase('preparing');
    setError(null);
    setStateNotice(null);
    notifyLifecycle('processing');
    try {
      const expectedIdentity = readPersistedCalculationState(
        window.localStorage,
      );
      const response = await prepareCalculation(modelVersionId);
      if (requestRevision !== identityRevisionRef.current) {
        return;
      }
      if (
        response.model_version_id !== modelVersionId ||
        response.workbook_version_id !== workbookVersionId
      ) {
        throw new Error(
          'Preparation response belongs to a different model or workbook.',
        );
      }
      setReadiness(response);
      if (isCalculationReady(response.status)) {
        await activateReadyCalculation(
          response,
          requestRevision,
          expectedIdentity,
        );
      } else if (response.status === 'preparing') {
        setPhase('preparing');
      } else if (response.status === 'not_prepared') {
        setPhase('not_prepared');
        notifyLifecycle('failed');
      } else {
        setPhase('failed');
        notifyLifecycle('failed');
      }
    } catch (caught) {
      if (requestRevision === identityRevisionRef.current) {
        setError(
          caught instanceof Error
            ? caught
            : new Error('Calculation preparation failed.'),
        );
        setPhase('failed');
        notifyLifecycle('failed');
      }
    }
  };

  const activeRun = overrideRun ?? baselineRun;
  const notifications = buildPreparationNotifications({
    uploadResult,
    readiness,
    activeRun,
    error,
    stateNotice,
  });
  const details = buildTechnicalDetails({
    uploadResult,
    readiness,
    baselineRun,
    overrideRun,
  });
  const hasWarnings = notifications.some(
    ({ severity }) => severity === 'warning',
  );
  const hasBlockingError =
    phase === 'failed' ||
    notifications.some(({ severity }) => severity === 'error');
  const displayPhaseLabel =
    phase === 'completed' && hasWarnings
      ? 'Completed with warnings'
      : phaseLabel(phase, readiness);
  const canPrepare =
    readiness?.status === 'not_prepared' ||
    readiness?.status === 'failed';
  const canRunBaseline =
    graphVersionId !== null &&
    baselineRun === null &&
    !baselineInFlightRef.current &&
    phase !== 'checking_readiness' &&
    phase !== 'preparing';

  return (
    <div className="space-y-4">
      {canPrepare || canRunBaseline ? (
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-d-border bg-d-card/45 px-5 py-4">
          <div>
            <h2 className="font-semibold text-white">
              Calculation preparation
            </h2>
            <p className="mt-1 text-sm text-d-muted">
              {phaseLabel(phase, readiness)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {canPrepare ? (
              <button
                type="button"
                onClick={() => void handlePrepare()}
                className="rounded-md bg-gold-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-gold-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-gold-300"
              >
                Retry preparation
              </button>
            ) : null}
            {canRunBaseline ? (
              <button
                type="button"
                onClick={() =>
                  void executeBaseline(
                    graphVersionId,
                    identityRevisionRef.current,
                  )
                }
                className="rounded-md bg-gold-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-gold-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-gold-300"
              >
                Run baseline
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      <CalculationRunSummary
        readiness={readiness}
        phaseLabel={displayPhaseLabel}
        hasWarnings={hasWarnings}
        hasError={hasBlockingError}
        details={details}
      />
      <PreparationNotifications notifications={notifications} />
    </div>
  );
}
