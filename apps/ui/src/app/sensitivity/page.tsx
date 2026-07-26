'use client';

import Link from 'next/link';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import FloatingAssistant from '../FloatingAssistant';
import { FixedSensitivityDashboard } from '@/components/sensitivity/FixedSensitivityDashboard';
import {
  getCalculationReadiness,
  getCalculationRunOutputs,
  runCalculation,
  runCalculationSensitivity,
} from '@/lib/api';
import type {
  CalculationRunOutputsResponse,
  CalculationSensitivityResponse,
} from '@/lib/calculation-api-types';
import {
  CALCULATION_STORAGE_KEYS,
  createGuardedSensitivityStorage,
  isCalculationStorageLockAvailable,
  persistSensitivityWorkbenchState,
  readPersistedCalculationState,
  readSensitivityWorkbenchDocument,
  type SensitivityWorkbenchDraft,
} from '@/lib/calculation-storage';
import {
  buildCanonicalOverrideCalculationRequest,
  buildSensitivityRequest,
  buildTornadoRows,
  buildTwoWayMatrix,
  canApplySensitivityResponse,
  canRetainSensitivityIdentity,
  formatSensitivityDelta,
  loadAllEditableNumericParameters,
  retainEligibleSensitivityDrivers,
  resolveSensitivitySelections,
  restoreSensitivityOutputProjection,
  type SensitivityAssumption,
} from '@/lib/sensitivity-analysis';
import {
  orderFixedDashboardAssumptions,
  promoteFixedDashboardDriver,
  resolveFixedDashboardCalculationMode,
  resolveFixedDashboardViewModel,
} from '@/lib/sensitivity-dashboard-view-model';
import { buildSensitivityOutputView } from '@/lib/sensitivity-output-adapter';

const MAX_TORNADO_DRIVERS = 12;
const SENSITIVITY_DEBOUNCE_MS = 400;
const STORAGE_RECONCILIATION_MS = 50;

interface WorkbenchState {
  assumptions: SensitivityAssumption[];
  overridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  selectedOutputId: string | null;
  rowDriverKey: string | null;
  columnDriverKey: string | null;
  outputs: CalculationRunOutputsResponse | null;
  analysis: CalculationSensitivityResponse | null;
}

type BootstrapWorkbenchResult = 'applied' | 'superseded' | 'failed';

interface ActiveIdentity {
  modelVersionId: string;
  graphVersionId: string;
}

type EmptyReason = 'model' | 'graph' | 'baseline' | 'outputs' | null;

const EMPTY_WORKBENCH: WorkbenchState = {
  assumptions: [],
  overridesByTarget: {},
  tornadoDriverKeys: [],
  selectedOutputId: null,
  rowDriverKey: null,
  columnDriverKey: null,
  outputs: null,
  analysis: null,
};

function isPercentage(
  unit: string | null,
  numberFormat: string | null,
): boolean {
  return unit?.trim() === '%' || numberFormat?.includes('%') === true;
}

function formatNumber(value: number, maximumFractionDigits = 4): string {
  return value.toLocaleString(undefined, {
    maximumFractionDigits,
    minimumFractionDigits: 0,
  });
}

function formatNumericOutput(
  value: number | null,
  unit: string | null,
  numberFormat: string | null,
): string {
  if (value === null || !Number.isFinite(value)) {
    return 'Unavailable';
  }
  if (isPercentage(unit, numberFormat)) {
    return `${formatNumber(value * 100)}%`;
  }
  return unit ? `${formatNumber(value)} ${unit}` : formatNumber(value);
}

function finiteDecimal(value: string): boolean {
  return value.trim() !== '' && Number.isFinite(Number(value));
}

function createWorkbenchDocumentRevision(): string {
  if (typeof window.crypto?.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function pruneInactiveSensitivitySelections(
  workbench: WorkbenchState,
): WorkbenchState {
  const tornadoDriverKeys = retainEligibleSensitivityDrivers(
    workbench.assumptions,
    workbench.overridesByTarget,
    workbench.tornadoDriverKeys,
  );
  return {
    ...workbench,
    tornadoDriverKeys,
    rowDriverKey: null,
    columnDriverKey: null,
    analysis: tornadoDriverKeys.length === 0 ? null : workbench.analysis,
  };
}

export default function SensitivityPage() {
  const [workbench, setWorkbench] =
    useState<WorkbenchState>(EMPTY_WORKBENCH);
  const [assumptionsExpanded, setAssumptionsExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [recalculating, setRecalculating] = useState(false);
  const [emptyReason, setEmptyReason] = useState<EmptyReason>(null);
  const [error, setError] = useState<Error | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const storageReconciliationTimerRef =
    useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestRevisionRef = useRef(0);
  const bootstrapRevisionRef = useRef(0);
  const activeIdentityRef = useRef<ActiveIdentity | null>(null);
  const workbenchSnapshotRef = useRef<WorkbenchState>(EMPTY_WORKBENCH);
  const persistedWorkbenchRef = useRef<WorkbenchState>(EMPTY_WORKBENCH);
  const workbenchDocumentRevisionRef = useRef<string | null>(null);

  function invalidatePersistedIdentity() {
    activeIdentityRef.current = null;
    workbenchDocumentRevisionRef.current = null;
    setRecalculating(false);
    setError(
      new Error(
        'The persisted model or run selection changed. Refresh before editing this workbench.',
      ),
    );
  }

  async function bootstrapWorkbench(): Promise<BootstrapWorkbenchResult> {
    const bootstrapRevision = ++bootstrapRevisionRef.current;
    const previousActiveIdentity = activeIdentityRef.current;
    requestRevisionRef.current += 1;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setLoading(true);
    setRecalculating(false);
    setError(null);
    setEmptyReason(null);

    const persisted = readPersistedCalculationState(window.localStorage);
    const canRetainPreviousIdentity = canRetainSensitivityIdentity(
      previousActiveIdentity,
      persisted,
    );
    if (!canRetainPreviousIdentity) {
      activeIdentityRef.current = null;
    }

    const clearForEmptyState = (reason: Exclude<EmptyReason, null>) => {
      activeIdentityRef.current = null;
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return;
      }
      setWorkbench(() => EMPTY_WORKBENCH);
      workbenchSnapshotRef.current = EMPTY_WORKBENCH;
      persistedWorkbenchRef.current = EMPTY_WORKBENCH;
      workbenchDocumentRevisionRef.current = null;
      setEmptyReason(reason);
      setLoading(false);
    };

    if (persisted.modelVersionId === null) {
      clearForEmptyState('model');
      return 'applied';
    }
    if (persisted.graphVersionId === null) {
      clearForEmptyState('graph');
      return 'applied';
    }
    if (persisted.baselineRunId === null) {
      clearForEmptyState('baseline');
      return 'applied';
    }

    const identity: ActiveIdentity = {
      modelVersionId: persisted.modelVersionId,
      graphVersionId: persisted.graphVersionId,
    };
    const bootstrapStorage = createGuardedSensitivityStorage(
      window.localStorage,
      persisted,
      () => bootstrapRevision === bootstrapRevisionRef.current,
    );

    try {
      const readiness = await getCalculationReadiness(identity.modelVersionId);
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return 'superseded';
      }
      if (!bootstrapStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return 'failed';
      }
      if (
        readiness.model_version_id !== identity.modelVersionId ||
        readiness.graph_version_id !== identity.graphVersionId ||
        !['ready', 'ready_with_warning'].includes(readiness.status)
      ) {
        activeIdentityRef.current = null;
        throw new Error(
          'Stored model and calculation graph no longer match calculation readiness.',
        );
      }

      const [assumptions, outputs] = await Promise.all([
        loadAllEditableNumericParameters(
          identity.modelVersionId,
          undefined,
          identity.graphVersionId,
        ),
        restoreSensitivityOutputProjection(bootstrapStorage, persisted),
      ]);
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return 'superseded';
      }
      if (!bootstrapStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return 'failed';
      }
      const restoredPersisted = readPersistedCalculationState(
        window.localStorage,
      );
      if (outputs === null) {
        clearForEmptyState('outputs');
        return 'applied';
      }
      if (
        outputs.model_version_id !== identity.modelVersionId ||
        outputs.graph_version_id !== identity.graphVersionId ||
        outputs.comparison_baseline_run_id !==
          restoredPersisted.baselineRunId ||
        outputs.calculation_run_id !==
          (restoredPersisted.overrideRunId ??
            restoredPersisted.baselineRunId)
      ) {
        activeIdentityRef.current = null;
        throw new Error(
          'Persisted output projection does not match the active model, graph, and baseline.',
        );
      }

      const restoredCurrentRunId =
        restoredPersisted.overrideRunId ?? restoredPersisted.baselineRunId;
      const storedDocument = readSensitivityWorkbenchDocument(
        bootstrapStorage,
        identity.modelVersionId,
        identity.graphVersionId,
        restoredPersisted.baselineRunId as string,
        restoredCurrentRunId as string,
      );
      const assumptionByKey = new Map(
        assumptions.map((assumption) => [
          assumption.targetKey,
          assumption,
        ]),
      );
      const overridesByTarget = Object.fromEntries(
        Object.entries(storedDocument?.overridesByTarget ?? {}).filter(
          ([targetKey, value]) =>
            assumptionByKey.has(targetKey) && finiteDecimal(value),
        ),
      );
      const outputView = buildSensitivityOutputView(outputs);
      const selectedOutputId = resolveFixedDashboardViewModel(
        outputView.kpis,
        storedDocument?.selectedOutputId ?? null,
      ).irrOutputId;
      const { tornadoDriverKeys } = resolveSensitivitySelections({
        assumptions,
        overridesByTarget,
        storedTornadoDriverKeys:
          storedDocument?.tornadoDriverKeys ?? null,
        storedRowDriverKey: null,
        storedColumnDriverKey: null,
        maxDrivers: MAX_TORNADO_DRIVERS,
      });

      const nextWorkbench: WorkbenchState = {
        assumptions,
        overridesByTarget,
        tornadoDriverKeys,
        selectedOutputId,
        rowDriverKey: null,
        columnDriverKey: null,
        outputs,
        analysis: null,
      };
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return 'superseded';
      }
      const storageLockAvailable = isCalculationStorageLockAvailable();
      activeIdentityRef.current = storageLockAvailable ? identity : null;
      workbenchSnapshotRef.current = nextWorkbench;
      persistedWorkbenchRef.current = nextWorkbench;
      workbenchDocumentRevisionRef.current =
        storedDocument?.revision ?? null;
      setWorkbench(() => nextWorkbench);
      setAssumptionsExpanded(false);
      if (!storageLockAvailable) {
        setError(
          new Error(
            'This browser cannot coordinate calculation storage across tabs. Results remain available to view, but sensitivity controls are disabled to prevent unpersisted calculation runs.',
          ),
        );
      }
      return 'applied';
    } catch (caught) {
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return 'superseded';
      }
      activeIdentityRef.current = null;
      setError(
        caught instanceof Error
          ? caught
          : new Error('Could not load the sensitivity workbench.'),
      );
      return 'failed';
    } finally {
      if (bootstrapRevision === bootstrapRevisionRef.current) {
        setLoading(false);
      }
    }
  }

  function scheduleAnalysis(nextWorkbench: WorkbenchState) {
    const identity = activeIdentityRef.current;
    const persisted = readPersistedCalculationState(window.localStorage);
    const revision = ++requestRevisionRef.current;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setError(null);

    const calculationMode = resolveFixedDashboardCalculationMode(
      nextWorkbench.selectedOutputId,
      nextWorkbench.tornadoDriverKeys.length,
    );
    if (
      identity === null ||
      (calculationMode === 'sensitivity' &&
        nextWorkbench.tornadoDriverKeys.length === 0)
    ) {
      setRecalculating(false);
      return;
    }
    if (
      persisted.modelVersionId !== identity.modelVersionId ||
      persisted.graphVersionId !== identity.graphVersionId ||
      persisted.baselineRunId === null
    ) {
      invalidatePersistedIdentity();
      return;
    }

    setRecalculating(true);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      void executeAnalysis(
        revision,
        identity,
        persisted,
        nextWorkbench,
      );
    }, SENSITIVITY_DEBOUNCE_MS);
  }

  async function executeAnalysis(
    revision: number,
    identity: ActiveIdentity,
    persisted: ReturnType<typeof readPersistedCalculationState>,
    requestWorkbench: WorkbenchState,
  ) {
    const stillCurrent = () => {
      const activeIdentity = activeIdentityRef.current;
      return (
        revision === requestRevisionRef.current &&
        activeIdentity?.modelVersionId === identity.modelVersionId &&
        activeIdentity.graphVersionId === identity.graphVersionId
      );
    };
    const guardedStorage = createGuardedSensitivityStorage(
      window.localStorage,
      persisted,
      stillCurrent,
    );

    try {
      if (!isCalculationStorageLockAvailable()) {
        activeIdentityRef.current = null;
        setError(
          new Error(
            'This browser cannot coordinate calculation storage across tabs. Sensitivity controls are disabled before calculation submission.',
          ),
        );
        return;
      }
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }

      const calculationMode = resolveFixedDashboardCalculationMode(
        requestWorkbench.selectedOutputId,
        requestWorkbench.tornadoDriverKeys.length,
      );
      let analysis: CalculationSensitivityResponse | null = null;
      let currentRunId: string;

      if (calculationMode === 'sensitivity') {
        const request = buildSensitivityRequest({
          graphVersionId: identity.graphVersionId,
          outputId: requestWorkbench.selectedOutputId as string,
          assumptions: requestWorkbench.assumptions,
          overridesByTarget: requestWorkbench.overridesByTarget,
          tornadoDriverKeys: requestWorkbench.tornadoDriverKeys,
          rowDriverKey: null,
          columnDriverKey: null,
        });
        if (request.drivers.length === 0) {
          throw new Error(
            'At least one non-zero tornado driver is required.',
          );
        }
        analysis = await runCalculationSensitivity(
          identity.modelVersionId,
          request,
        );
        if (
          !canApplySensitivityResponse(analysis, {
            requestRevision: revision,
            currentRevision: requestRevisionRef.current,
            modelVersionId: identity.modelVersionId,
            graphVersionId: identity.graphVersionId,
            outputId: request.output_id,
          }) ||
          analysis.comparison_baseline_run_id !== persisted.baselineRunId ||
          !stillCurrent()
        ) {
          return;
        }
        currentRunId = analysis.current_run_id;
      } else {
        const calculation = await runCalculation(
          identity.modelVersionId,
          buildCanonicalOverrideCalculationRequest({
            graphVersionId: identity.graphVersionId,
            assumptions: requestWorkbench.assumptions,
            overridesByTarget: requestWorkbench.overridesByTarget,
          }),
        );
        if (
          !stillCurrent() ||
          calculation.model_version_id !== identity.modelVersionId ||
          calculation.graph_version_id !== identity.graphVersionId ||
          !['completed', 'completed_with_warning'].includes(
            calculation.status,
          )
        ) {
          return;
        }
        currentRunId = calculation.calculation_run_id;
      }
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }

      const outputs = await getCalculationRunOutputs(currentRunId);
      if (!stillCurrent()) {
        return;
      }
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }
      if (
        outputs.calculation_run_id !== currentRunId ||
        outputs.model_version_id !== identity.modelVersionId ||
        outputs.graph_version_id !== identity.graphVersionId ||
        outputs.comparison_baseline_run_id !== persisted.baselineRunId
      ) {
        return;
      }

      const nextSelectedOutputId = resolveFixedDashboardViewModel(
        buildSensitivityOutputView(outputs).kpis,
        requestWorkbench.selectedOutputId,
      ).irrOutputId;
      const document: SensitivityWorkbenchDraft = {
        modelVersionId: identity.modelVersionId,
        graphVersionId: identity.graphVersionId,
        overridesByTarget: requestWorkbench.overridesByTarget,
        tornadoDriverKeys: requestWorkbench.tornadoDriverKeys,
        selectedOutputId: nextSelectedOutputId,
        rowDriverKey: null,
        columnDriverKey: null,
      };
      const appliedWorkbench: WorkbenchState = {
        ...requestWorkbench,
        selectedOutputId: nextSelectedOutputId,
        rowDriverKey: null,
        columnDriverKey: null,
        analysis,
        outputs,
      };
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }
      const persistence = await persistSensitivityWorkbenchState(
        window.localStorage,
        {
          expectedIdentity: persisted,
          expectedDocumentRevision:
            workbenchDocumentRevisionRef.current,
          nextDocumentRevision: createWorkbenchDocumentRevision(),
          response: {
            model_version_id: outputs.model_version_id,
            graph_version_id: outputs.graph_version_id,
            comparison_baseline_run_id:
              outputs.comparison_baseline_run_id,
            current_run_id: outputs.calculation_run_id,
          },
          document,
          isCurrent: stillCurrent,
        },
      );
      if (persistence.status === 'superseded') {
        return;
      }
      if (persistence.status === 'conflict') {
        const reconciled = await bootstrapWorkbench();
        if (reconciled === 'superseded') {
          return;
        }
        setError(
          new Error(
            reconciled === 'applied'
              ? 'This sensitivity workbench changed in another browser tab. The latest persisted result was reloaded without creating another run.'
              : 'This sensitivity workbench changed in another browser tab, but the automatic GET-only reload failed. Refresh before editing.',
          ),
        );
        return;
      }
      if (persistence.status === 'unavailable') {
        const previousWorkbench = persistedWorkbenchRef.current;
        workbenchSnapshotRef.current = previousWorkbench;
        setWorkbench(() => previousWorkbench);
        const storageCoordinationFailed =
          persistence.reason === 'lock_unavailable' ||
          persistence.reason === 'lock_failed';
        if (
          persistence.storageState === 'unknown' ||
          storageCoordinationFailed
        ) {
          activeIdentityRef.current = null;
          workbenchDocumentRevisionRef.current = null;
        }
        setError(
          new Error(
            persistence.storageState === 'unknown'
              ? 'Browser storage failed and rollback could not be verified. The calculated result was not applied; controls are disabled until you refresh.'
              : storageCoordinationFailed
                ? 'Browser storage coordination failed. The calculated result was not applied; controls are disabled before another calculation can be submitted.'
                : 'The sensitivity result was calculated, but browser storage could not save it. The last persisted result remains displayed.',
          ),
        );
        return;
      }
      workbenchDocumentRevisionRef.current = persistence.revision;
      persistedWorkbenchRef.current = appliedWorkbench;
      workbenchSnapshotRef.current = appliedWorkbench;
      setWorkbench(() => appliedWorkbench);
    } catch (caught) {
      if (!stillCurrent()) {
        return;
      }
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }
      setError(
        caught instanceof Error
          ? caught
          : new Error('Sensitivity analysis failed.'),
      );
    } finally {
      if (stillCurrent()) {
        setRecalculating(false);
      }
    }
  }

  function applyUserUpdate(
    update: (current: WorkbenchState) => WorkbenchState,
  ) {
    const nextWorkbench = pruneInactiveSensitivitySelections(
      update(workbenchSnapshotRef.current),
    );
    workbenchSnapshotRef.current = nextWorkbench;
    setWorkbench(() => nextWorkbench);
    scheduleAnalysis(nextWorkbench);
  }

  useEffect(() => {
    const reconciliationKeys = new Set<string>(
      Object.values(CALCULATION_STORAGE_KEYS),
    );
    const handleStorage = (event: StorageEvent) => {
      if (
        event.storageArea !== window.localStorage ||
        (event.key !== null && !reconciliationKeys.has(event.key))
      ) {
        return;
      }
      requestRevisionRef.current += 1;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (storageReconciliationTimerRef.current !== null) {
        clearTimeout(storageReconciliationTimerRef.current);
      }
      setRecalculating(false);
      storageReconciliationTimerRef.current = setTimeout(() => {
        storageReconciliationTimerRef.current = null;
        void bootstrapWorkbench();
      }, STORAGE_RECONCILIATION_MS);
    };
    window.addEventListener('storage', handleStorage);
    void bootstrapWorkbench();
    return () => {
      window.removeEventListener('storage', handleStorage);
      bootstrapRevisionRef.current += 1;
      requestRevisionRef.current += 1;
      activeIdentityRef.current = null;
      workbenchDocumentRevisionRef.current = null;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (storageReconciliationTimerRef.current !== null) {
        clearTimeout(storageReconciliationTimerRef.current);
        storageReconciliationTimerRef.current = null;
      }
    };
  }, []);

  const outputView = useMemo(
    () =>
      workbench.outputs
        ? buildSensitivityOutputView(workbench.outputs)
        : null,
    [workbench.outputs],
  );
  const assumptionsByTarget = useMemo(
    () =>
      new Map(
        workbench.assumptions.map((assumption) => [
          assumption.targetKey,
          assumption,
        ]),
      ),
    [workbench.assumptions],
  );
  const tornadoRows = useMemo(
    () =>
      workbench.analysis
        ? buildTornadoRows(workbench.analysis, assumptionsByTarget)
        : [],
    [assumptionsByTarget, workbench.analysis],
  );
  const matrix = useMemo(
    () =>
      workbench.analysis
        ? buildTwoWayMatrix(workbench.analysis, assumptionsByTarget)
        : null,
    [assumptionsByTarget, workbench.analysis],
  );
  const dashboard = useMemo(
    () =>
      resolveFixedDashboardViewModel(
        outputView?.kpis ?? [],
        workbench.selectedOutputId,
      ),
    [outputView, workbench.selectedOutputId],
  );
  const orderedAssumptions = useMemo(
    () =>
      orderFixedDashboardAssumptions(
        workbench.assumptions,
        workbench.analysis === null ? null : tornadoRows,
      ),
    [tornadoRows, workbench.analysis, workbench.assumptions],
  );
  const analyzedOutput = workbench.analysis?.selected_output ?? null;
  const irrSlot =
    dashboard.slots.find((slot) => slot.key === 'irr') ?? null;
  const analyzedOutputLabel =
    analyzedOutput?.label ?? irrSlot?.displayLabel ?? 'IRR';
  const analyzedOutputUnit =
    analyzedOutput?.unit ?? irrSlot?.kpi?.unit ?? null;
  const analyzedNumberFormat =
    analyzedOutput?.number_format ?? irrSlot?.kpi?.numberFormat ?? null;
  const analysisUnavailableReason =
    dashboard.irrOutputId === null
      ? 'Neither Project IRR nor Equity IRR is available as a numeric canonical output. KPI cards still recalculate, while IRR sensitivity cases are not generated.'
      : null;
  const impactsByTarget = useMemo(
    () =>
      Object.fromEntries(
        tornadoRows.map((row) => [row.targetKey, row.impact]),
      ),
    [tornadoRows],
  );

  const formatAxisValue = useCallback(
    (targetKey: string, value: string): string => {
      const assumption = assumptionsByTarget.get(targetKey);
      const numericValue = Number(value);
      if (!Number.isFinite(numericValue)) {
        return 'Unavailable';
      }
      if (assumption?.unit?.trim() === '%') {
        return `${formatNumber(numericValue * 100)}%`;
      }
      return assumption?.unit
        ? `${formatNumber(numericValue)} ${assumption.unit}`
        : formatNumber(numericValue);
    },
    [assumptionsByTarget],
  );
  const formatAnalyzedOutputValue = useCallback(
    (value: number | null) =>
      formatNumericOutput(
        value,
        analyzedOutputUnit,
        analyzedNumberFormat,
      ),
    [analyzedNumberFormat, analyzedOutputUnit],
  );
  const formatAnalyzedOutputDelta = useCallback(
    (value: number) =>
      formatSensitivityDelta(
        value,
        analyzedOutputUnit,
        analyzedNumberFormat,
      ),
    [analyzedNumberFormat, analyzedOutputUnit],
  );

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-d-muted">
        Loading canonical sensitivity workbench…
      </div>
    );
  }

  if (emptyReason !== null) {
    const explanation = {
      model: 'No canonical calculation model is stored in this browser session.',
      graph: 'The stored model does not have a prepared calculation graph.',
      baseline:
        'A persisted zero-override baseline calculation is required before analysis.',
      outputs:
        'The stored baseline has no matching persisted output projection.',
    }[emptyReason];
    return (
      <div className="mx-auto max-w-2xl rounded-lg border border-d-border bg-d-card p-8 text-center">
        <h1 className="text-xl font-semibold text-white">
          Sensitivity workbench is not ready
        </h1>
        <p className="mt-3 text-sm text-d-muted">{explanation}</p>
        <p className="mt-2 text-sm text-d-muted">
          Reloading this page never creates a baseline automatically.
        </p>
        <Link
          href="/"
          className="mt-5 inline-block rounded bg-gold-500 px-4 py-2 text-sm font-semibold text-white hover:bg-gold-600"
        >
          Go to calculation flow
        </Link>
      </div>
    );
  }

  if (outputView === null) {
    return (
      <div className="mx-auto max-w-2xl rounded-lg border border-red-700/60 bg-red-900/20 p-6 text-red-200">
        <h1 className="text-lg font-semibold">Workbench could not load</h1>
        <p className="mt-2 text-sm">
          {error?.message ?? 'No persisted output projection was returned.'}
        </p>
        <button
          type="button"
          onClick={() => void bootstrapWorkbench()}
          className="mt-4 rounded border border-red-400/50 px-4 py-2 text-sm hover:bg-red-900/30"
        >
          Retry GET-only refresh
        </button>
      </div>
    );
  }

  return (
    <>
      <FixedSensitivityDashboard
        dashboard={dashboard}
        assumptions={orderedAssumptions}
        overridesByTarget={workbench.overridesByTarget}
        tornadoRows={tornadoRows}
        matrix={matrix}
        expanded={assumptionsExpanded}
        recalculating={recalculating}
        errorMessage={error?.message ?? null}
        controlsDisabled={activeIdentityRef.current === null}
        calculationRunId={outputView.calculationRunId}
        analysisOutputLabel={analyzedOutputLabel}
        analysisUnavailableReason={analysisUnavailableReason}
        onToggleExpanded={() =>
          setAssumptionsExpanded((current) => !current)
        }
        onValueChange={(targetKey, value) => {
          if (!finiteDecimal(value)) {
            return;
          }
          applyUserUpdate((current) => ({
            ...current,
            overridesByTarget: {
              ...current.overridesByTarget,
              [targetKey]: value,
            },
            tornadoDriverKeys: promoteFixedDashboardDriver({
              assumptions: current.assumptions,
              currentDriverKeys: current.tornadoDriverKeys,
              changedTargetKey: targetKey,
              impactsByTarget,
              maxDrivers: MAX_TORNADO_DRIVERS,
            }),
          }));
        }}
        onReset={(targetKey) =>
          applyUserUpdate((current) => {
            const nextOverrides = { ...current.overridesByTarget };
            delete nextOverrides[targetKey];
            return { ...current, overridesByTarget: nextOverrides };
          })
        }
        onResetAll={() =>
          applyUserUpdate((current) => ({
            ...current,
            overridesByTarget: {},
          }))
        }
        onRefresh={() => void bootstrapWorkbench()}
        formatAxisValue={formatAxisValue}
        formatAnalyzedOutputValue={formatAnalyzedOutputValue}
        formatAnalyzedOutputDelta={formatAnalyzedOutputDelta}
      />
      <FloatingAssistant
        tabKey="sensitivity"
        pageContext="Fixed canonical sensitivity workbench with stable investment KPIs, dynamic assumptions, deterministic IRR cases, and persisted comparisons"
      />
    </>
  );
}
