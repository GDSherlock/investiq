'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  getCalculationInputs,
  getCalculationReadiness,
  getCalculationRun,
  prepareCalculation,
  runCalculation,
} from '@/lib/api';
import {
  CalculationApiError,
  type CalculationInput,
  type CalculationReadinessResponse,
  type CalculationRunResponse,
  type CalculationUiPhase,
} from '@/lib/calculation-api-types';
import {
  buildBaselineRequest,
  buildParameterOverrideRequest,
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
import { diffCalculationRunValues } from '@/lib/calculation-value-utils';

import {
  CalculationInputPanel,
  type OverrideSubmissionReceipt,
} from './CalculationInputPanel';
import { CalculationResultsDiff } from './CalculationResultsDiff';

interface CalculationPreparationPanelProps {
  modelVersionId: string;
  workbookVersionId: string;
  restoreFromStorage: boolean;
}

type EditableNumericParameter = CalculationInput & {
  target_kind: 'parameter';
  current_value: { value_type: 'number'; value: string };
  editable: true;
};

function isEditableNumericParameter(
  input: CalculationInput,
): input is EditableNumericParameter {
  return (
    input.target_kind === 'parameter' &&
    input.editable === true &&
    input.current_value.value_type === 'number'
  );
}

function ErrorDetails({ error }: { error: Error }) {
  if (error instanceof CalculationApiError) {
    return (
      <dl className="mt-2 grid gap-1 font-mono text-xs">
        <div>
          <dt className="inline text-red-300">code: </dt>
          <dd className="inline">{error.code}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">message: </dt>
          <dd className="inline">{error.message}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">retryable: </dt>
          <dd className="inline">{String(error.retryable)}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">resource_id: </dt>
          <dd className="inline">{error.resourceId ?? 'null'}</dd>
        </div>
      </dl>
    );
  }
  return <p className="mt-2 text-sm">{error.message}</p>;
}

function ReadinessErrorDetails({
  readiness,
}: {
  readiness: CalculationReadinessResponse;
}) {
  if (!readiness.error) {
    return null;
  }
  return (
    <div className="mt-4 rounded border border-red-700/60 bg-red-900/20 p-3 text-red-200">
      <p className="font-semibold">Readiness error detail</p>
      <dl className="mt-2 grid gap-1 font-mono text-xs">
        <div>
          <dt className="inline text-red-300">code: </dt>
          <dd className="inline">{readiness.error.code}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">message: </dt>
          <dd className="inline">{readiness.error.message}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">retryable: </dt>
          <dd className="inline">{String(readiness.error.retryable)}</dd>
        </div>
        <div>
          <dt className="inline text-red-300">resource_id: </dt>
          <dd className="inline">
            {readiness.error.resource_id ?? 'null'}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function RunSummary({
  title,
  run,
}: {
  title: string;
  run: CalculationRunResponse;
}) {
  return (
    <div className="rounded border border-d-border bg-d-bg p-4">
      <h4 className="font-semibold text-white">{title}</h4>
      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-d-muted">Run status</dt>
          <dd className="text-white">{run.status}</dd>
        </div>
        <div>
          <dt className="text-d-muted">Calculated</dt>
          <dd className="text-white">
            {run.summary.calculated_formula_cells}
          </dd>
        </div>
        <div>
          <dt className="text-d-muted">Reused</dt>
          <dd className="text-white">{run.summary.reused_formula_cells}</dd>
        </div>
        <div>
          <dt className="text-d-muted">Dirty</dt>
          <dd className="text-white">{run.summary.dirty_formula_cells}</dd>
        </div>
      </dl>
      <dl className="mt-3 space-y-1 break-all font-mono text-xs text-d-muted">
        <div>
          <dt className="inline">run_id: </dt>
          <dd className="inline text-slate-200">{run.calculation_run_id}</dd>
        </div>
        <div>
          <dt className="inline">graph_version_id: </dt>
          <dd className="inline text-slate-200">{run.graph_version_id}</dd>
        </div>
        <div>
          <dt className="inline">base_run_id: </dt>
          <dd className="inline text-slate-200">{run.base_run_id ?? 'null'}</dd>
        </div>
      </dl>
    </div>
  );
}

export function CalculationPreparationPanel({
  modelVersionId,
  workbookVersionId,
  restoreFromStorage,
}: CalculationPreparationPanelProps) {
  const [phase, setPhase] =
    useState<CalculationUiPhase>('checking_readiness');
  const [readiness, setReadiness] =
    useState<CalculationReadinessResponse | null>(null);
  const [graphVersionId, setGraphVersionId] = useState<string | null>(null);
  const [inputs, setInputs] = useState<CalculationInput[]>([]);
  const [selectedInputId, setSelectedInputId] = useState('');
  const [draftValue, setDraftValue] = useState('');
  const [baselineRun, setBaselineRun] =
    useState<CalculationRunResponse | null>(null);
  const [overrideRun, setOverrideRun] =
    useState<CalculationRunResponse | null>(null);
  const [lastOverrideReceipt, setLastOverrideReceipt] =
    useState<OverrideSubmissionReceipt | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [stateNotice, setStateNotice] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const identityRevisionRef = useRef(0);
  const baselineInFlightRef = useRef(false);
  const overrideInFlightRef = useRef(false);
  const overrideRequestRevisionRef = useRef(0);

  const applyDefaultInput = useCallback((loadedInputs: CalculationInput[]) => {
    const firstEditableNumber = loadedInputs.find(isEditableNumericParameter);
    if (firstEditableNumber) {
      setSelectedInputId(firstEditableNumber.target_id);
      setDraftValue(firstEditableNumber.current_value.value);
    } else {
      setSelectedInputId('');
      setDraftValue('');
    }
  }, []);

  const executeBaseline = useCallback(
    async (targetGraphVersionId: string, requestRevision: number) => {
      if (baselineInFlightRef.current) {
        return;
      }
      baselineInFlightRef.current = true;
      setPhase('running_baseline');
      setError(null);
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
        setPhase('ready_for_override');
      } catch (caught) {
        if (requestRevision === identityRevisionRef.current) {
          setError(
            caught instanceof Error
              ? caught
              : new Error('Baseline calculation failed.'),
          );
          setPhase('failed');
        }
      } finally {
        baselineInFlightRef.current = false;
      }
    },
    [modelVersionId, workbookVersionId],
  );

  const restorePersistedRuns = useCallback(
    async (
      targetGraphVersionId: string,
      initialIdentity: ReturnType<typeof readPersistedCalculationState>,
      requestRevision: number,
    ) => {
      const { baselineRunId, overrideRunId } = initialIdentity;
      const expectedIdentity = initialIdentity;
      const requests: {
        kind: 'baseline' | 'override';
        runId: string;
      }[] = [];
      if (baselineRunId) {
        requests.push({ kind: 'baseline', runId: baselineRunId });
      }
      if (overrideRunId) {
        requests.push({ kind: 'override', runId: overrideRunId });
      }

      const settled = await Promise.allSettled(
        requests.map(({ runId }) => getCalculationRun(runId)),
      );
      if (requestRevision !== identityRevisionRef.current) {
        return;
      }

      let restoredBaseline: CalculationRunResponse | null = null;
      let restoredOverride: CalculationRunResponse | null = null;
      const notices: string[] = [];
      let firstError: Error | null = null;

      for (let index = 0; index < settled.length; index += 1) {
        const result = settled[index];
        const { kind } = requests[index];
        if (result.status === 'rejected') {
          const caught =
            result.reason instanceof Error
              ? result.reason
              : new Error(`Could not reload the stored ${kind} run.`);
          if (caught instanceof CalculationApiError && caught.status === 404) {
            const removed = await removePersistedCalculationRunId(
              window.localStorage,
              kind,
              expectedIdentity,
            );
            if (removed) {
              setBaselineRun(
                kind === 'override' ? restoredBaseline : null,
              );
              setOverrideRun(null);
              setError(null);
              setStateNotice(
                `Stored ${kind} run was not found and was cleared. Remaining run results were not applied from the stale reload batch.`,
              );
              setPhase('ready_for_override');
              return;
            } else {
              setStateNotice(
                `Stored calculation identity changed while the ${kind} run was loading; no persisted state was modified.`,
              );
              setError(
                new Error(
                  'Stored calculation identity changed while persisted runs were loading.',
                ),
              );
              setPhase('failed');
              return;
            }
          } else {
            firstError ??= caught;
          }
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
            return;
          }
          setBaselineRun(
            kind === 'override' ? restoredBaseline : null,
          );
          setOverrideRun(null);
          setError(null);
          setStateNotice(
            `${
              reconciled.notice ??
              `Stored ${kind} run was cleared.`
            } Remaining run results were not applied from the stale reload batch.`,
          );
          setPhase('ready_for_override');
          return;
        }
        if (kind === 'baseline') {
          restoredBaseline = result.value;
        } else {
          restoredOverride = result.value;
        }
      }

      setBaselineRun(restoredBaseline);
      setOverrideRun(restoredOverride);
      setError(firstError);
      if (notices.length > 0) {
        setStateNotice(notices.join(' '));
      } else {
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
      }
      setPhase(restoredOverride ? 'completed' : 'ready_for_override');
    },
    [modelVersionId],
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
      if (identityMatches && !graphMatches) {
        setStateNotice(
          'Stored calculation graph differed from current readiness and its run IDs were cleared. No calculation was submitted.',
        );
      }

      setPhase('loading_inputs');
      const responseInputs = await getCalculationInputs(modelVersionId, {
        targetKind: 'parameter',
        editableOnly: true,
        limit: 100,
      });
      if (requestRevision !== identityRevisionRef.current) {
        return;
      }
      if (
        responseInputs.model_version_id !== modelVersionId ||
        responseInputs.graph_version_id !== targetGraphVersionId
      ) {
        throw new Error(
          'Calculation inputs belong to a different model or graph.',
        );
      }
      setInputs(responseInputs.inputs);
      applyDefaultInput(responseInputs.inputs);

      if (hadPersistedRuns && graphMatches) {
        await restorePersistedRuns(
          targetGraphVersionId,
          expectedIdentity,
          requestRevision,
        );
        return;
      }
      if (hadPersistedRuns) {
        setPhase('ready_for_override');
        return;
      }
      if (restoreFromStorage) {
        setStateNotice(
          'Restored calculation readiness and inputs from stored version IDs. No calculation was submitted.',
        );
        setPhase('ready_for_override');
        return;
      }
      if (shouldAutoRunBaseline(expectedIdentity)) {
        await executeBaseline(targetGraphVersionId, requestRevision);
      }
    },
    [
      applyDefaultInput,
      executeBaseline,
      modelVersionId,
      workbookVersionId,
      restoreFromStorage,
      restorePersistedRuns,
    ],
  );

  useEffect(() => {
    const requestRevision = ++identityRevisionRef.current;
    let cancelled = false;

    async function initialize() {
      setPhase('checking_readiness');
      setError(null);
      setStateNotice(null);
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
        switch (response.status) {
          case 'not_prepared':
            setPhase('not_prepared');
            break;
          case 'preparing':
            setPhase('preparing');
            break;
          case 'model_not_ready':
            setPhase('uploaded');
            break;
          case 'failed':
            setPhase('failed');
            break;
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
        }
      }
    }

    void initialize();
    return () => {
      cancelled = true;
    };
  }, [
    activateReadyCalculation,
    modelVersionId,
    refreshToken,
    workbookVersionId,
  ]);

  const handlePrepare = async () => {
    const requestRevision = identityRevisionRef.current;
    setPhase('preparing');
    setError(null);
    try {
      const expectedIdentity = readPersistedCalculationState(
        window.localStorage,
      );
      const response = await prepareCalculation(modelVersionId);
      if (requestRevision !== identityRevisionRef.current) {
        return;
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
      } else {
        setPhase(response.status === 'not_prepared' ? 'not_prepared' : 'failed');
      }
    } catch (caught) {
      if (requestRevision === identityRevisionRef.current) {
        setError(
          caught instanceof Error
            ? caught
            : new Error('Calculation preparation failed.'),
        );
        setPhase('failed');
      }
    }
  };

  const handleSelectInput = (targetId: string) => {
    setSelectedInputId(targetId);
    const selected = inputs.find((input) => input.target_id === targetId);
    if (selected?.current_value.value_type === 'number') {
      setDraftValue(selected.current_value.value);
    } else {
      setDraftValue('');
    }
  };

  const handleOverride = async () => {
    if (
      overrideInFlightRef.current ||
      !graphVersionId ||
      !selectedInputId ||
      !baselineRun
    ) {
      return;
    }
    const selected = inputs.find(
      (input) => input.target_id === selectedInputId,
    );
    if (!selected || !isEditableNumericParameter(selected)) {
      setError(new Error('Select an editable numeric canonical parameter.'));
      return;
    }

    let request;
    try {
      request = buildParameterOverrideRequest(
        graphVersionId,
        selected.target_id,
        draftValue,
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught
          : new Error('Invalid numeric override.'),
      );
      return;
    }

    const submittedValue = request.overrides[0].value;
    const baselineForComparison = baselineRun;
    const expectedIdentity = readPersistedCalculationState(
      window.localStorage,
    );
    if (
      expectedIdentity.workbookVersionId !== workbookVersionId ||
      expectedIdentity.modelVersionId !== modelVersionId ||
      expectedIdentity.graphVersionId !== graphVersionId ||
      expectedIdentity.baselineRunId !==
        baselineForComparison.calculation_run_id
    ) {
      setError(
        new Error(
          'Stored calculation identity changed before the override request.',
        ),
      );
      return;
    }
    overrideInFlightRef.current = true;
    const overrideRevision = ++overrideRequestRevisionRef.current;
    setPhase('running_override');
    setError(null);
    setLastOverrideReceipt(null);
    try {
      const run = await runCalculation(modelVersionId, request);
      if (
        overrideRevision !== overrideRequestRevisionRef.current ||
        run.model_version_id !== modelVersionId ||
        run.graph_version_id !== graphVersionId
      ) {
        return;
      }
      const persisted = await persistCalculationRunId(
        window.localStorage,
        'override',
        run.calculation_run_id,
        expectedIdentity,
      );
      if (!persisted) {
        throw new Error(
          'Stored calculation identity changed while the override was running.',
        );
      }
      setOverrideRun(run);
      setLastOverrideReceipt({
        label: selected.label,
        originalValue: selected.current_value.value,
        submittedValue:
          submittedValue.value_type === 'number'
            ? submittedValue.value
            : draftValue.trim(),
        unit: selected.unit,
        runId: run.calculation_run_id,
        status: run.status,
        changedFormulaValues: diffCalculationRunValues(
          baselineForComparison.values,
          run.values,
        ).length,
      });
      setPhase('completed');
    } catch (caught) {
      if (overrideRevision === overrideRequestRevisionRef.current) {
        setError(
          caught instanceof Error
            ? caught
            : new Error('Override calculation failed.'),
        );
        setPhase('ready_for_override');
      }
    } finally {
      overrideInFlightRef.current = false;
    }
  };

  const handleManualReload = async (kind: 'baseline' | 'override') => {
    if (!graphVersionId) {
      return;
    }
    const persisted = readPersistedCalculationState(window.localStorage);
    if (
      persisted.workbookVersionId !== workbookVersionId ||
      persisted.modelVersionId !== modelVersionId ||
      persisted.graphVersionId !== graphVersionId
    ) {
      setStateNotice(
        'Stored calculation identity changed before the run reload; no persisted state was modified.',
      );
      return;
    }
    const runId =
      kind === 'baseline'
        ? persisted.baselineRunId
        : persisted.overrideRunId;
    if (!runId) {
      setStateNotice(`No persisted ${kind} run ID is available to reload.`);
      return;
    }
    setError(null);
    try {
      const run = await getCalculationRun(runId);
      const reconciled = await reconcileStoredRun(
        window.localStorage,
        kind,
        run,
        modelVersionId,
        graphVersionId,
        persisted,
      );
      if (!reconciled.isCurrent) {
        setStateNotice(reconciled.notice);
        return;
      }
      if (kind === 'baseline') {
        setBaselineRun(run);
      } else {
        setOverrideRun(run);
      }
      setStateNotice(
        `Reloaded persisted ${kind} run ${runId} via GET; no calculation was submitted.`,
      );
      setPhase(kind === 'override' ? 'completed' : 'ready_for_override');
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught
          : new Error(`Could not reload ${kind} run.`),
      );
    }
  };

  const persistedState =
    typeof window === 'undefined'
      ? null
      : readPersistedCalculationState(window.localStorage);
  const canPrepare =
    readiness?.status === 'not_prepared' || readiness?.status === 'failed';
  const canRunManualBaseline =
    graphVersionId !== null &&
    inputs.length > 0 &&
    baselineRun === null &&
    phase !== 'running_baseline' &&
    phase !== 'loading_inputs';

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <section className="rounded-lg border border-d-border bg-d-card p-6 shadow">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-white">
              Calculation vertical slice
            </h2>
            <p className="mt-1 text-sm text-d-muted">
              Phase: <span className="font-mono text-white">{phase}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={() => setRefreshToken((value) => value + 1)}
            disabled={
              phase === 'checking_readiness' ||
              phase === 'preparing' ||
              phase === 'running_baseline' ||
              phase === 'running_override'
            }
            className="rounded border border-d-border px-3 py-2 text-sm text-white hover:bg-d-hover disabled:opacity-50"
          >
            Check readiness again
          </button>
        </div>

        <dl className="mt-4 grid gap-2 break-all font-mono text-xs md:grid-cols-2">
          <div>
            <dt className="text-d-muted">model_version_id</dt>
            <dd className="text-white">{modelVersionId}</dd>
          </div>
          <div>
            <dt className="text-d-muted">workbook_version_id</dt>
            <dd className="text-white">{workbookVersionId}</dd>
          </div>
          <div>
            <dt className="text-d-muted">graph_version_id</dt>
            <dd className="text-white">{graphVersionId ?? 'not prepared'}</dd>
          </div>
          <div>
            <dt className="text-d-muted">readiness</dt>
            <dd className="text-white">{readiness?.status ?? 'loading'}</dd>
          </div>
        </dl>

        {readiness ? (
          <div className="mt-4 grid gap-2 text-sm sm:grid-cols-4">
            <div className="rounded bg-d-bg p-3">
              <div className="text-d-muted">Formula total</div>
              <div className="text-xl text-white">
                {readiness.summary.formula_cells_total}
              </div>
            </div>
            <div className="rounded bg-d-bg p-3">
              <div className="text-d-muted">Supported</div>
              <div className="text-xl text-white">
                {readiness.summary.formula_cells_supported}
              </div>
            </div>
            <div className="rounded bg-d-bg p-3">
              <div className="text-d-muted">Graph nodes</div>
              <div className="text-xl text-white">
                {readiness.summary.graph_nodes}
              </div>
            </div>
            <div className="rounded bg-d-bg p-3">
              <div className="text-d-muted">Graph edges</div>
              <div className="text-xl text-white">
                {readiness.summary.graph_edges}
              </div>
            </div>
          </div>
        ) : null}

        {readiness?.status === 'ready_with_warning' ? (
          <div className="mt-4 rounded border border-yellow-700/60 bg-yellow-900/20 p-3 text-sm text-yellow-200">
            <p className="font-semibold">Calculation ready with warnings</p>
            {readiness.warnings.length > 0 ? (
              <ul className="mt-1 list-disc pl-5">
                {readiness.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {readiness?.status === 'model_not_ready' ? (
          <p className="mt-4 rounded border border-yellow-700/60 bg-yellow-900/20 p-3 text-sm text-yellow-300">
            The model has not been materialized. Calculation preparation is
            unavailable.
          </p>
        ) : null}

        {readiness?.status === 'preparing' ? (
          <p className="mt-4 text-sm text-d-muted">
            Calculation preparation is in progress.
          </p>
        ) : null}

        {readiness ? (
          <ReadinessErrorDetails readiness={readiness} />
        ) : null}

        {stateNotice ? (
          <p className="mt-4 rounded border border-blue-700/50 bg-blue-900/20 p-3 text-sm text-blue-200">
            {stateNotice}
          </p>
        ) : null}

        {error ? (
          <div className="mt-4 rounded border border-red-700/60 bg-red-900/20 p-3 text-red-200">
            <p className="font-semibold">Calculation request failed</p>
            <ErrorDetails error={error} />
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-2">
          {canPrepare ? (
            <button
              type="button"
              onClick={() => void handlePrepare()}
              disabled={phase === 'preparing'}
              className="rounded bg-gold-500 px-4 py-2 font-semibold text-white hover:bg-gold-600 disabled:opacity-50"
            >
              {readiness?.status === 'failed'
                || phase === 'failed'
                ? 'Retry preparation'
                : 'Prepare calculation'}
            </button>
          ) : null}
          {canRunManualBaseline ? (
            <button
              type="button"
              onClick={() =>
                void executeBaseline(
                  graphVersionId,
                  identityRevisionRef.current,
                )
              }
              className="rounded bg-gold-500 px-4 py-2 font-semibold text-white hover:bg-gold-600"
            >
              Run baseline calculation
            </button>
          ) : null}
          {persistedState?.baselineRunId ? (
            <button
              type="button"
              onClick={() => void handleManualReload('baseline')}
              className="rounded border border-d-border px-4 py-2 text-sm text-white hover:bg-d-hover"
            >
              Reload baseline run
            </button>
          ) : null}
          {persistedState?.overrideRunId ? (
            <button
              type="button"
              onClick={() => void handleManualReload('override')}
              className="rounded border border-d-border px-4 py-2 text-sm text-white hover:bg-d-hover"
            >
              Reload override run
            </button>
          ) : null}
        </div>
      </section>

      {baselineRun || overrideRun ? (
        <section className="rounded-lg border border-d-border bg-d-card p-6 shadow">
          <h3 className="text-lg font-semibold text-white">Run summaries</h3>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {baselineRun ? (
              <RunSummary title="Baseline run" run={baselineRun} />
            ) : null}
            {overrideRun ? (
              <RunSummary title="Override run" run={overrideRun} />
            ) : null}
          </div>
        </section>
      ) : null}

      {baselineRun ? (
        <CalculationInputPanel
          inputs={inputs}
          selectedInputId={selectedInputId}
              draftValue={draftValue}
              disabled={phase === 'running_override'}
              lastOverrideReceipt={lastOverrideReceipt}
              onSelect={handleSelectInput}
          onDraftValueChange={setDraftValue}
          onSubmit={() => void handleOverride()}
        />
      ) : null}

      {baselineRun && overrideRun ? (
        <CalculationResultsDiff
          baselineRun={baselineRun}
          overrideRun={overrideRun}
        />
      ) : null}
    </div>
  );
}
