'use client';

import Link from 'next/link';
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import FloatingAssistant from '../FloatingAssistant';
import { SensitivityAssumptionPanel } from '@/components/sensitivity/SensitivityAssumptionPanel';
import { SensitivityTornadoChart } from '@/components/sensitivity/SensitivityTornadoChart';
import { SensitivityTwoWayMatrix } from '@/components/sensitivity/SensitivityTwoWayMatrix';
import {
  getCalculationReadiness,
  getCalculationRunOutputs,
  runCalculationSensitivity,
} from '@/lib/api';
import type {
  CalculationRunOutputsResponse,
  CalculationSensitivityResponse,
  CalculationTypedValue,
} from '@/lib/calculation-api-types';
import {
  SENSITIVITY_WORKBENCH_VERSION,
  createGuardedSensitivityStorage,
  persistSensitivityRunSelection,
  persistSensitivityWorkbenchDocument,
  readPersistedCalculationState,
  readSensitivityWorkbenchDocument,
  type SensitivityWorkbenchDocument,
} from '@/lib/calculation-storage';
import {
  buildSensitivityRequest,
  buildTornadoRows,
  buildTwoWayMatrix,
  canApplySensitivityResponse,
  canRetainSensitivityIdentity,
  deriveSliderSpec,
  formatSensitivityDelta,
  isSensitivityCatalogIdentityError,
  loadAllEditableNumericParameters,
  retainEligibleSensitivityDrivers,
  resolveSensitivitySelections,
  restoreSensitivityOutputProjection,
  selectDefaultSensitivityOutput,
  type SensitivityAssumption,
} from '@/lib/sensitivity-analysis';
import {
  buildSensitivityOutputView,
  type SensitivityKpi,
  type SensitivityProjectedValue,
  type SensitivitySeries,
} from '@/lib/sensitivity-output-adapter';

const MAX_TORNADO_DRIVERS = 12;
const SENSITIVITY_DEBOUNCE_MS = 400;

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

function formatTypedValue(
  value: CalculationTypedValue,
  unit: string | null,
  numberFormat: string | null,
): string {
  switch (value.value_type) {
    case 'number':
      return formatNumericOutput(Number(value.value), unit, numberFormat);
    case 'boolean':
      return value.value ? 'True' : 'False';
    case 'blank':
      return 'Blank';
    case 'date_serial':
      return value.iso_evidence ?? value.value;
    case 'error':
      return value.error_code;
    default:
      return value.value;
  }
}

function formatProjectedValue(
  projected: SensitivityProjectedValue,
  unit: string | null,
  numberFormat: string | null,
): string {
  if (
    projected.availabilityStatus !== 'available' ||
    projected.typedValue === null
  ) {
    return 'Unavailable';
  }
  return formatTypedValue(projected.typedValue, unit, numberFormat);
}

function formatAbsoluteChange(kpi: SensitivityKpi): string {
  if (kpi.absoluteChange === null) {
    return 'Unavailable';
  }
  const sign = kpi.absoluteChange > 0 ? '+' : '';
  if (isPercentage(kpi.unit, kpi.numberFormat)) {
    return `${sign}${formatNumber(kpi.absoluteChange * 100)} pp`;
  }
  return `${sign}${formatNumber(kpi.absoluteChange)}`;
}

function formatRelativeChange(change: number | null): string {
  if (change === null) {
    return '—';
  }
  const sign = change > 0 ? '+' : '';
  return `${sign}${formatNumber(change)}%`;
}

function unavailableReason(kpi: SensitivityKpi): string {
  return (
    kpi.current.unavailableReason ??
    kpi.baseline.unavailableReason ??
    kpi.supportStatus
  );
}

function currentAssumptionValue(
  assumption: SensitivityAssumption,
  overridesByTarget: Record<string, string>,
): string {
  return overridesByTarget[assumption.targetKey] ?? assumption.currentValue;
}

function finiteDecimal(value: string): boolean {
  return value.trim() !== '' && Number.isFinite(Number(value));
}

function pruneInactiveSensitivitySelections(
  workbench: WorkbenchState,
): WorkbenchState {
  const rangeCapableKeys = new Set(
    workbench.assumptions
      .filter(
        (assumption) =>
          deriveSliderSpec(
            currentAssumptionValue(
              assumption,
              workbench.overridesByTarget,
            ),
          ).kind === 'range',
      )
      .map((assumption) => assumption.targetKey),
  );
  const rowDriverKey =
    workbench.rowDriverKey !== null &&
    rangeCapableKeys.has(workbench.rowDriverKey)
      ? workbench.rowDriverKey
      : null;
  const columnDriverKey =
    workbench.columnDriverKey !== null &&
    workbench.columnDriverKey !== rowDriverKey &&
    rangeCapableKeys.has(workbench.columnDriverKey)
      ? workbench.columnDriverKey
      : null;
  const tornadoDriverKeys = retainEligibleSensitivityDrivers(
    workbench.assumptions,
    workbench.overridesByTarget,
    workbench.tornadoDriverKeys,
  );
  return {
    ...workbench,
    tornadoDriverKeys,
    rowDriverKey,
    columnDriverKey,
    analysis: tornadoDriverKeys.length === 0 ? null : workbench.analysis,
  };
}

const KpiCard = memo(function KpiCard({ kpi }: { kpi: SensitivityKpi }) {
  const available = kpi.current.availabilityStatus === 'available';
  return (
    <article className="rounded-lg border border-d-border bg-d-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-d-muted">
            {kpi.label}
          </p>
          {kpi.scenario ? (
            <p className="mt-0.5 text-[10px] text-d-muted">{kpi.scenario}</p>
          ) : null}
        </div>
        <span
          className={`rounded px-2 py-0.5 text-[10px] font-medium ${
            available
              ? 'bg-green-900/30 text-green-300'
              : 'bg-amber-900/30 text-amber-300'
          }`}
        >
          {available ? 'Available' : 'Unavailable'}
        </span>
      </div>
      <p
        className={`mt-3 text-2xl font-bold ${
          available ? 'text-gold-400' : 'text-d-muted'
        }`}
      >
        {formatProjectedValue(kpi.current, kpi.unit, kpi.numberFormat)}
      </p>
      {available ? (
        <p className="mt-2 text-xs text-d-muted">
          Baseline{' '}
          <span className="font-mono text-slate-200">
            {formatProjectedValue(kpi.baseline, kpi.unit, kpi.numberFormat)}
          </span>{' '}
          · Δ{' '}
          <span className="font-mono text-gold-300">
            {formatAbsoluteChange(kpi)}
          </span>
        </p>
      ) : (
        <p className="mt-2 break-words font-mono text-[11px] text-amber-200">
          {unavailableReason(kpi)}
        </p>
      )}
    </article>
  );
});

const SeriesChartCard = memo(function SeriesChartCard({
  series,
}: {
  series: SensitivitySeries;
}) {
  const data = series.points.map((point) => ({
    period: point.period ?? `Period ${point.periodIndex + 1}`,
    baseline: point.baseline.numericValue,
    current: point.current.numericValue,
  }));
  const chartable = data.some(
    (point) => point.baseline !== null || point.current !== null,
  );

  return (
    <article className="min-w-0 overflow-hidden rounded-lg border border-d-border bg-d-card p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white">{series.label}</h3>
          <p className="mt-1 text-xs text-d-muted">
            {series.businessRole} · {series.unit ?? 'Unitless'} ·{' '}
            {series.points.length} periods
          </p>
        </div>
        <span
          className={`rounded px-2 py-1 text-[10px] font-medium ${
            series.availabilityStatus === 'available'
              ? 'bg-green-900/30 text-green-300'
              : series.availabilityStatus === 'partial'
                ? 'bg-amber-900/30 text-amber-300'
                : 'bg-red-900/30 text-red-300'
          }`}
        >
          {series.availabilityStatus}
        </span>
      </div>

      {chartable ? (
        <div className="mt-4">
          <div
            className="h-64"
            role="img"
            aria-label={`${series.label} time-series chart comparing baseline and current values across ${series.points.length} periods`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data}
                margin={{ top: 8, right: 12, bottom: 8, left: 0 }}
              >
                <CartesianGrid stroke="rgba(148,163,184,0.12)" />
                <XAxis
                  dataKey="period"
                  stroke="#94a3b8"
                  tick={{ fontSize: 11 }}
                />
                <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} width={56} />
                <Tooltip
                  contentStyle={{
                    background: '#111827',
                    border: '1px solid #334155',
                    borderRadius: 6,
                  }}
                  labelStyle={{ color: '#e2e8f0' }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="baseline"
                  name="Baseline"
                  stroke="#94a3b8"
                  strokeDasharray="5 4"
                  strokeWidth={2}
                  connectNulls={false}
                />
                <Line
                  type="monotone"
                  dataKey="current"
                  name="Current"
                  stroke="#f4c430"
                  strokeWidth={2.5}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ul className="sr-only">
            {series.points.map((point) => (
              <li key={point.financialSeriesValueId}>
                {point.period ?? `Period ${point.periodIndex + 1}`}: baseline{' '}
                {formatProjectedValue(
                  point.baseline,
                  series.unit,
                  point.numberFormat,
                )}
                ; current{' '}
                {formatProjectedValue(
                  point.current,
                  series.unit,
                  point.numberFormat,
                )}
                .
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-4 rounded border border-amber-800/40 bg-amber-900/10 p-4 text-sm text-amber-200">
          This canonical series is unavailable. No substitute value is shown.
        </p>
      )}

      {series.unavailableCurrentReasons.length > 0 ? (
        <div className="mt-3 rounded border border-amber-800/40 bg-amber-900/10 p-3">
          <p className="text-xs font-medium text-amber-200">
            Unavailable current-period reasons
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-amber-100">
            {series.unavailableCurrentReasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-3 border-t border-d-border pt-3 text-xs text-d-muted">
        Changed periods:{' '}
        <span className="font-semibold text-slate-200">
          {series.changedPointCount}
        </span>
        {series.unavailableCurrentPointCount > 0
          ? ` · ${series.unavailableCurrentPointCount} unavailable`
          : ''}
      </p>
    </article>
  );
});

export default function SensitivityPage() {
  const [workbench, setWorkbench] =
    useState<WorkbenchState>(EMPTY_WORKBENCH);
  const [loading, setLoading] = useState(true);
  const [recalculating, setRecalculating] = useState(false);
  const [emptyReason, setEmptyReason] = useState<EmptyReason>(null);
  const [error, setError] = useState<Error | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestRevisionRef = useRef(0);
  const bootstrapRevisionRef = useRef(0);
  const activeIdentityRef = useRef<ActiveIdentity | null>(null);
  const workbenchSnapshotRef = useRef<WorkbenchState>(EMPTY_WORKBENCH);

  function invalidatePersistedIdentity() {
    activeIdentityRef.current = null;
    setRecalculating(false);
    setError(
      new Error(
        'The persisted model or run selection changed. Refresh before editing this workbench.',
      ),
    );
  }

  async function bootstrapWorkbench() {
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
    if (persisted.modelVersionId === null) {
      activeIdentityRef.current = null;
      if (bootstrapRevision === bootstrapRevisionRef.current) {
        setWorkbench(() => EMPTY_WORKBENCH);
        workbenchSnapshotRef.current = EMPTY_WORKBENCH;
        setEmptyReason('model');
        setLoading(false);
      }
      return;
    }
    if (persisted.graphVersionId === null) {
      activeIdentityRef.current = null;
      if (bootstrapRevision === bootstrapRevisionRef.current) {
        setWorkbench(() => EMPTY_WORKBENCH);
        workbenchSnapshotRef.current = EMPTY_WORKBENCH;
        setEmptyReason('graph');
        setLoading(false);
      }
      return;
    }
    if (persisted.baselineRunId === null) {
      activeIdentityRef.current = null;
      if (bootstrapRevision === bootstrapRevisionRef.current) {
        setWorkbench(() => EMPTY_WORKBENCH);
        workbenchSnapshotRef.current = EMPTY_WORKBENCH;
        setEmptyReason('baseline');
        setLoading(false);
      }
      return;
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
        return;
      }
      if (!bootstrapStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
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

      const storedDocument = readSensitivityWorkbenchDocument(
        bootstrapStorage,
        identity.modelVersionId,
        identity.graphVersionId,
      );
      const [assumptions, outputs] = await Promise.all([
        loadAllEditableNumericParameters(
          identity.modelVersionId,
          undefined,
          identity.graphVersionId,
        ),
        restoreSensitivityOutputProjection(
          bootstrapStorage,
          persisted,
        ),
      ]);
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return;
      }
      if (!bootstrapStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }
      const restoredPersisted = readPersistedCalculationState(
        window.localStorage,
      );
      if (outputs === null) {
        activeIdentityRef.current = null;
        setEmptyReason('outputs');
        return;
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
      const availableOutputIds = new Set(
        outputView.kpis
          .filter(
            (kpi) =>
              kpi.current.availabilityStatus === 'available' &&
              kpi.current.numericValue !== null,
          )
          .map((kpi) => kpi.outputId),
      );
      const selectedOutputId =
        storedDocument?.selectedOutputId !== null &&
        storedDocument?.selectedOutputId !== undefined &&
        availableOutputIds.has(storedDocument.selectedOutputId)
          ? storedDocument.selectedOutputId
          : selectDefaultSensitivityOutput(outputView.kpis);

      const {
        tornadoDriverKeys,
        rowDriverKey,
        columnDriverKey,
      } = resolveSensitivitySelections({
        assumptions,
        overridesByTarget,
        storedTornadoDriverKeys:
          storedDocument?.tornadoDriverKeys ?? null,
        storedRowDriverKey: storedDocument?.rowDriverKey ?? null,
        storedColumnDriverKey:
          storedDocument?.columnDriverKey ?? null,
        maxDrivers: MAX_TORNADO_DRIVERS,
      });

      const nextWorkbench: WorkbenchState = {
        assumptions,
        overridesByTarget,
        tornadoDriverKeys,
        selectedOutputId,
        rowDriverKey,
        columnDriverKey,
        outputs,
        analysis: null,
      };
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return;
      }
      activeIdentityRef.current = identity;
      workbenchSnapshotRef.current = nextWorkbench;
      setWorkbench(() => nextWorkbench);
    } catch (caught) {
      if (bootstrapRevision !== bootstrapRevisionRef.current) {
        return;
      }
      if (isSensitivityCatalogIdentityError(caught)) {
        activeIdentityRef.current = null;
      }
      setError(
        caught instanceof Error
          ? caught
          : new Error('Could not load the sensitivity workbench.'),
      );
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

    if (
      identity === null ||
      nextWorkbench.selectedOutputId === null ||
      nextWorkbench.tornadoDriverKeys.length === 0
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
      const request = buildSensitivityRequest({
        graphVersionId: identity.graphVersionId,
        outputId: requestWorkbench.selectedOutputId as string,
        assumptions: requestWorkbench.assumptions,
        overridesByTarget: requestWorkbench.overridesByTarget,
        tornadoDriverKeys: requestWorkbench.tornadoDriverKeys,
        rowDriverKey: requestWorkbench.rowDriverKey,
        columnDriverKey: requestWorkbench.columnDriverKey,
      });
      if (request.drivers.length === 0) {
        throw new Error(
          'At least one non-zero tornado driver is required.',
        );
      }
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }

      const analysis = await runCalculationSensitivity(
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
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }

      const outputs = await getCalculationRunOutputs(analysis.current_run_id);
      if (!stillCurrent()) {
        return;
      }
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }
      if (
        outputs.calculation_run_id !== analysis.current_run_id ||
        outputs.model_version_id !== analysis.model_version_id ||
        outputs.graph_version_id !== analysis.graph_version_id ||
        outputs.comparison_baseline_run_id !==
          analysis.comparison_baseline_run_id
      ) {
        return;
      }

      const document: SensitivityWorkbenchDocument = {
        version: SENSITIVITY_WORKBENCH_VERSION,
        modelVersionId: identity.modelVersionId,
        graphVersionId: identity.graphVersionId,
        overridesByTarget: requestWorkbench.overridesByTarget,
        tornadoDriverKeys: requestWorkbench.tornadoDriverKeys,
        selectedOutputId: requestWorkbench.selectedOutputId,
        rowDriverKey: requestWorkbench.rowDriverKey,
        columnDriverKey: requestWorkbench.columnDriverKey,
      };
      const appliedWorkbench: WorkbenchState = {
        ...requestWorkbench,
        analysis,
        outputs,
      };
      if (!guardedStorage.matchesCurrent()) {
        invalidatePersistedIdentity();
        return;
      }
      workbenchSnapshotRef.current = appliedWorkbench;
      setWorkbench(() => appliedWorkbench);
      persistSensitivityRunSelection(guardedStorage, analysis);
      persistSensitivityWorkbenchDocument(guardedStorage, document);
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
    void bootstrapWorkbench();
    return () => {
      bootstrapRevisionRef.current += 1;
      requestRevisionRef.current += 1;
      activeIdentityRef.current = null;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
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
  const availableNumericKpis = useMemo(
    () =>
      outputView?.kpis.filter(
        (kpi) =>
          kpi.current.availabilityStatus === 'available' &&
          kpi.current.numericValue !== null,
      ) ?? [],
    [outputView],
  );
  const selectedKpi =
    availableNumericKpis.find(
      (kpi) => kpi.outputId === workbench.selectedOutputId,
    ) ?? null;
  const analyzedOutput = workbench.analysis?.selected_output ?? null;
  const analyzedOutputLabel =
    analyzedOutput?.label ?? selectedKpi?.label ?? 'Output';
  const analyzedOutputUnit =
    analyzedOutput?.unit ?? selectedKpi?.unit ?? null;
  const analyzedNumberFormat =
    analyzedOutput?.number_format ?? selectedKpi?.numberFormat ?? null;
  const analysisMatchesSelectedOutput =
    analyzedOutput?.output_id === workbench.selectedOutputId;
  const driverSelectionPending =
    workbench.tornadoDriverKeys.length === 0;
  const rangeCapableAssumptions = useMemo(
    () =>
      workbench.assumptions.filter(
        (assumption) =>
          deriveSliderSpec(
            currentAssumptionValue(
              assumption,
              workbench.overridesByTarget,
            ),
          ).kind === 'range',
      ),
    [workbench.assumptions, workbench.overridesByTarget],
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
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Sensitivity Analysis
          </h1>
          <p className="mt-1 text-sm text-d-muted">
            Real deterministic cases from canonical assumptions and outputs
          </p>
          <p className="mt-2 break-all font-mono text-[11px] text-d-muted">
            run_id: {outputView.calculationRunId}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            aria-live="polite"
            className={`rounded px-3 py-1 text-xs font-medium ${
              recalculating || error !== null || driverSelectionPending
                ? 'bg-amber-900/30 text-amber-200'
                : 'bg-green-900/30 text-green-300'
            }`}
          >
            {recalculating
              ? 'Recalculating…'
              : error !== null || driverSelectionPending
                ? 'Last successful result retained'
                : 'Persisted results'}
          </span>
          <button
            type="button"
            onClick={() => void bootstrapWorkbench()}
            className="rounded border border-d-border px-3 py-1.5 text-xs text-white hover:border-gold-400 hover:bg-d-hover"
          >
            Refresh with GETs
          </button>
        </div>
      </header>

      {error ? (
        <div
          role="alert"
          className="rounded border border-red-700/60 bg-red-900/20 p-3 text-sm text-red-200"
        >
          {error.message}
        </div>
      ) : null}

      {driverSelectionPending ? (
        <div
          role="status"
          className="rounded border border-amber-800/60 bg-amber-900/15 p-3 text-sm text-amber-100"
        >
          Tornado analysis is pending a non-zero driver. Enter a non-zero
          assumption value to enable recalculation; the displayed outputs are
          the last successful persisted result.
        </div>
      ) : null}

      <fieldset
        disabled={activeIdentityRef.current === null}
        className="grid min-w-0 items-start gap-5 disabled:cursor-not-allowed lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)]"
      >
        <legend className="sr-only">
          Canonical sensitivity controls and results
        </legend>
        <SensitivityAssumptionPanel
          assumptions={workbench.assumptions}
          overridesByTarget={workbench.overridesByTarget}
          tornadoDriverKeys={workbench.tornadoDriverKeys}
          maxDrivers={MAX_TORNADO_DRIVERS}
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
          onToggleDriver={(targetKey, selected) =>
            applyUserUpdate((current) => {
              const driverKeys = new Set(current.tornadoDriverKeys);
              if (selected) {
                const assumption = current.assumptions.find(
                  (candidate) => candidate.targetKey === targetKey,
                );
                if (
                  assumption === undefined ||
                  deriveSliderSpec(
                    currentAssumptionValue(
                      assumption,
                      current.overridesByTarget,
                    ),
                  ).kind !== 'range'
                ) {
                  return current;
                }
                if (driverKeys.size >= MAX_TORNADO_DRIVERS) {
                  return current;
                }
                driverKeys.add(targetKey);
              } else {
                driverKeys.delete(targetKey);
              }
              return {
                ...current,
                tornadoDriverKeys: Array.from(driverKeys),
              };
            })
          }
        />

        <div className="min-w-0 space-y-5">
          <section>
            <div className="mb-3">
              <h2 className="text-base font-semibold text-white">
                Current canonical outputs
              </h2>
              <p className="mt-1 text-xs text-d-muted">
                Every scalar output returned by the persisted current run
              </p>
            </div>
            {outputView.kpis.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {outputView.kpis.map((kpi) => (
                  <KpiCard key={kpi.outputId} kpi={kpi} />
                ))}
              </div>
            ) : (
              <p className="rounded-lg border border-d-border bg-d-card p-5 text-sm text-d-muted">
                No canonical scalar output was returned for this model.
              </p>
            )}
          </section>

          <section className="rounded-lg border border-d-border bg-d-card p-5 shadow-sm">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-white">
                  One-way driver impact
                </h2>
                <p className="mt-1 text-xs text-d-muted">
                  Signed low/high deltas around the persisted current case
                </p>
              </div>
              <label className="w-full text-xs text-d-muted sm:w-72">
                Selected canonical output
                <select
                  value={workbench.selectedOutputId ?? ''}
                  onChange={(event) =>
                    applyUserUpdate((current) => ({
                      ...current,
                      selectedOutputId: event.target.value || null,
                    }))
                  }
                  className="mt-1 w-full rounded border border-d-border bg-d-bg px-3 py-2 text-sm text-white focus-visible:border-gold-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400"
                >
                  {availableNumericKpis.map((kpi) => (
                    <option key={kpi.outputId} value={kpi.outputId}>
                      {kpi.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {workbench.analysis !== null &&
            !analysisMatchesSelectedOutput ? (
              <p
                role="status"
                className="mt-4 rounded border border-amber-800/50 bg-amber-900/10 p-3 text-xs text-amber-100"
              >
                Showing the last successful analysis for{' '}
                <span className="font-semibold">{analyzedOutputLabel}</span>.
                The selected output{' '}
                <span className="font-semibold">
                  {selectedKpi?.label ?? 'is unavailable'}
                </span>{' '}
                has not replaced it.
              </p>
            ) : null}
            <div className="mt-4">
              <SensitivityTornadoChart
                rows={tornadoRows}
                outputLabel={analyzedOutputLabel}
                formatValue={formatAnalyzedOutputValue}
                formatDelta={formatAnalyzedOutputDelta}
              />
            </div>
          </section>

          <div className="grid gap-5 xl:grid-cols-2">
            <section className="min-w-0 overflow-x-auto rounded-lg border border-d-border bg-d-card p-5 shadow-sm">
              <h2 className="text-base font-semibold text-white">
                Baseline vs current
              </h2>
              <p className="mt-1 text-xs text-d-muted">
                Scalar comparison against the explicit zero-override run
              </p>
              {outputView.kpis.length > 0 ? (
                <table className="mt-4 w-full min-w-[34rem] text-sm">
                  <thead>
                    <tr className="border-b border-d-border text-xs uppercase tracking-wide text-d-muted">
                      <th className="pb-2 text-left font-medium">Output</th>
                      <th className="pb-2 text-right font-medium">Baseline</th>
                      <th className="pb-2 text-right font-medium">Current</th>
                      <th className="pb-2 text-right font-medium">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {outputView.kpis.map((kpi) => (
                      <tr
                        key={kpi.outputId}
                        className="border-b border-d-border"
                      >
                        <th
                          scope="row"
                          className="py-3 text-left font-medium text-white"
                        >
                          {kpi.label}
                        </th>
                        <td className="py-3 text-right font-mono text-slate-300">
                          {formatProjectedValue(
                            kpi.baseline,
                            kpi.unit,
                            kpi.numberFormat,
                          )}
                        </td>
                        <td className="py-3 text-right font-mono text-white">
                          {formatProjectedValue(
                            kpi.current,
                            kpi.unit,
                            kpi.numberFormat,
                          )}
                        </td>
                        <td className="py-3 text-right font-mono text-gold-300">
                          {formatAbsoluteChange(kpi)}
                          {kpi.absoluteChange !== null ? (
                            <span className="text-[10px] text-d-muted">
                              {' ('}
                              {formatRelativeChange(kpi.percentageChange)}
                              {')'}
                            </span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="mt-4 text-sm text-d-muted">
                  No scalar outputs to compare.
                </p>
              )}
            </section>

            <section className="min-w-0 rounded-lg border border-d-border bg-d-card p-5 shadow-sm">
              <h2 className="text-base font-semibold text-white">
                Two-way sensitivity
              </h2>
              <p className="mt-1 text-xs text-d-muted">
                Actual Cartesian engine cases for two canonical assumptions
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-d-muted">
                  Row assumption
                  <select
                    value={workbench.rowDriverKey ?? ''}
                    onChange={(event) =>
                      applyUserUpdate((current) => ({
                        ...current,
                        rowDriverKey: event.target.value || null,
                      }))
                    }
                    className="mt-1 w-full rounded border border-d-border bg-d-bg px-3 py-2 text-sm text-white focus-visible:border-gold-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400"
                  >
                    <option value="">None</option>
                    {rangeCapableAssumptions.map((assumption) => (
                      <option
                        key={assumption.targetKey}
                        value={assumption.targetKey}
                      >
                        {assumption.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-d-muted">
                  Column assumption
                  <select
                    value={workbench.columnDriverKey ?? ''}
                    onChange={(event) =>
                      applyUserUpdate((current) => ({
                        ...current,
                        columnDriverKey: event.target.value || null,
                      }))
                    }
                    className="mt-1 w-full rounded border border-d-border bg-d-bg px-3 py-2 text-sm text-white focus-visible:border-gold-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400"
                  >
                    <option value="">None</option>
                    {rangeCapableAssumptions.map((assumption) => (
                      <option
                        key={assumption.targetKey}
                        value={assumption.targetKey}
                      >
                        {assumption.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="mt-4">
                <SensitivityTwoWayMatrix
                  matrix={matrix}
                  outputLabel={analyzedOutputLabel}
                  formatAxisValue={formatAxisValue}
                  formatOutputValue={formatAnalyzedOutputValue}
                />
              </div>
            </section>
          </div>
        </div>
      </fieldset>

      <section>
        <div className="mb-3">
          <h2 className="text-base font-semibold text-white">
            Canonical time-series outputs
          </h2>
          <p className="mt-1 text-xs text-d-muted">
            Every returned series is shown dynamically, including unclassified
            model outputs.
          </p>
        </div>
        {outputView.series.length > 0 ? (
          <div className="grid gap-4 xl:grid-cols-2">
            {outputView.series.map((series) => (
              <SeriesChartCard key={series.outputId} series={series} />
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-d-border bg-d-card p-5 text-sm text-d-muted">
            No canonical time-series output was returned for this model.
          </p>
        )}
      </section>

      <FloatingAssistant
        tabKey="sensitivity"
        pageContext="Canonical sensitivity workbench with persisted output comparisons, deterministic one-way cases, a two-way matrix, and dynamic time series"
      />
    </div>
  );
}
