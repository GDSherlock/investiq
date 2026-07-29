'use client';

import { useEffect, useRef } from 'react';

import type { FixedDashboardViewModel } from '../../lib/sensitivity-dashboard-view-model';
import { visibleFixedDashboardAssumptions } from '../../lib/sensitivity-dashboard-view-model';
import { DEFAULT_TORNADO_DRIVER_LIMIT } from '../../lib/sensitivity-analysis';
import type {
  SensitivityAssumption,
  SensitivityMatrixView,
  SensitivityTornadoRow,
} from '../../lib/sensitivity-analysis';
import { formatUiNumber as formatNumber } from '../../lib/ui-number-format';

import { SensitivityAssumptionPanel } from './SensitivityAssumptionPanel';
import { SensitivityTornadoChart } from './SensitivityTornadoChart';
import { SensitivityTwoWayMatrix } from './SensitivityTwoWayMatrix';

interface FixedSensitivityDashboardProps {
  dashboard: FixedDashboardViewModel;
  assumptions: SensitivityAssumption[];
  overridesByTarget: Record<string, string>;
  tornadoRows: SensitivityTornadoRow[];
  matrix: SensitivityMatrixView | null;
  expanded: boolean;
  recalculating: boolean;
  analysisRefreshing?: boolean;
  initialAnalysisStatus?: string;
  analysisStale?: boolean;
  analysisRunDisabled?: boolean;
  estimatedOutputIds?: string[];
  errorMessage: string | null;
  controlsDisabled: boolean;
  calculationRunId: string;
  analysisOutputLabel: string;
  analysisUnavailableReason: string | null;
  twoWayUnavailableReason: string | null;
  tornadoDriverKeys?: string[];
  eligibleTornadoDrivers?: SensitivityAssumption[];
  pendingTornadoReplacementTargetKey?: string | null;
  onToggleExpanded: () => void;
  onValueChange: (targetKey: string, value: string) => void;
  onReset: (targetKey: string) => void;
  onResetAll: () => void;
  onRefresh: () => void;
  onRunAnalysis?: () => void;
  onTornadoDriverToggle?: (targetKey: string) => void;
  onTornadoDriverReplace?: (outgoingTargetKey: string) => void;
  onCancelTornadoDriverReplacement?: () => void;
  formatAxisValue: (targetKey: string, value: string) => string;
  formatAnalyzedOutputValue: (value: number | null) => string;
  formatAnalyzedOutputDelta: (value: number) => string;
}

function isPercentage(
  unit: string | null,
  numberFormat: string | null,
): boolean {
  return unit?.trim() === '%' || numberFormat?.includes('%') === true;
}

function formatKpiValue(
  numericValue: number | null,
  unit: string | null,
  numberFormat: string | null,
): string {
  if (numericValue === null || !Number.isFinite(numericValue)) {
    return 'Unavailable';
  }
  if (isPercentage(unit, numberFormat)) {
    return `${formatNumber(numericValue * 100)}%`;
  }
  return unit ? `${formatNumber(numericValue)} ${unit}` : formatNumber(numericValue);
}

function formatKpiDelta(
  value: number | null,
  unit: string | null,
  numberFormat: string | null,
): string {
  if (value === null || !Number.isFinite(value)) {
    return 'Unavailable';
  }
  const sign = value > 0 ? '+' : '';
  return isPercentage(unit, numberFormat)
    ? `${sign}${formatNumber(value * 100)} pp`
    : `${sign}${formatNumber(value)}`;
}

function formatAssumptionValue(
  assumption: SensitivityAssumption,
  overridesByTarget: Record<string, string>,
): string {
  const raw = overridesByTarget[assumption.targetKey] ?? assumption.currentValue;
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) {
    return 'Unavailable';
  }
  const displayed = assumption.unit?.trim() === '%' ? numeric * 100 : numeric;
  const formatted = formatNumber(displayed);
  return assumption.unit ? `${formatted} ${assumption.unit}` : formatted;
}

export function FixedSensitivityDashboard({
  dashboard,
  assumptions,
  overridesByTarget,
  tornadoRows,
  matrix,
  expanded,
  recalculating,
  analysisRefreshing = false,
  initialAnalysisStatus,
  analysisStale = false,
  analysisRunDisabled = false,
  estimatedOutputIds = [],
  errorMessage,
  controlsDisabled,
  calculationRunId,
  analysisOutputLabel,
  analysisUnavailableReason,
  twoWayUnavailableReason,
  tornadoDriverKeys = [],
  eligibleTornadoDrivers = [],
  pendingTornadoReplacementTargetKey = null,
  onToggleExpanded,
  onValueChange,
  onReset,
  onResetAll,
  onRefresh,
  onRunAnalysis = () => undefined,
  onTornadoDriverToggle = () => undefined,
  onTornadoDriverReplace = () => undefined,
  onCancelTornadoDriverReplacement = () => undefined,
  formatAxisValue,
  formatAnalyzedOutputValue,
  formatAnalyzedOutputDelta,
}: FixedSensitivityDashboardProps) {
  const visibleAssumptions = visibleFixedDashboardAssumptions(
    assumptions,
    expanded,
  );
  const assumptionScrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!expanded && assumptionScrollRef.current) {
      assumptionScrollRef.current.scrollTop = 0;
    }
  }, [expanded]);
  const irrSlot = dashboard.slots.find((slot) => slot.key === 'irr') ?? null;
  const irrKpi = irrSlot?.kpi ?? null;
  const liveSlots = dashboard.slots.slice(0, 4);
  const estimatedIds = new Set(estimatedOutputIds);
  const analysisButtonLabel = analysisRefreshing
    ? 'Running analysis…'
    : tornadoRows.length > 0
      ? 'Refresh analysis'
      : 'Run analysis';
  const analysisDisabled =
    controlsDisabled ||
    recalculating ||
    analysisRefreshing ||
    analysisRunDisabled;
  const selectedTornadoDrivers = new Set(tornadoDriverKeys);
  const pendingReplacementDriver = eligibleTornadoDrivers.find(
    (assumption) =>
      assumption.targetKey === pendingTornadoReplacementTargetKey,
  );

  return (
    <div className="min-w-0 space-y-5" data-testid="fixed-sensitivity-dashboard">
      {errorMessage ? (
        <div
          role="alert"
          className="rounded-lg border border-red-700/60 bg-red-900/20 px-4 py-3 text-sm text-red-200"
        >
          {errorMessage}
        </div>
      ) : null}

      <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <aside className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-1">
          <section className="rounded-lg border border-d-border bg-d-card p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-200">
              Decision Confidence
            </p>
            <p className="mt-4 text-3xl font-bold text-white">
              {irrKpi
                ? formatKpiValue(
                    irrKpi.current.numericValue,
                    irrKpi.unit,
                    irrKpi.numberFormat,
                  )
                : 'Unavailable'}
            </p>
            {irrKpi && estimatedIds.has(irrKpi.outputId) ? (
              <p className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-sky-300">
                Estimated
              </p>
            ) : null}
            <p className="mt-3 text-sm font-medium text-amber-200">
              Threshold unavailable
            </p>
            <p className="mt-2 text-xs leading-5 text-d-muted">
              This model does not provide structured hurdle or covenant
              metadata.
            </p>
          </section>

          <section className="rounded-lg border border-d-border bg-d-card p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-200">
              Live Model KPIs
            </p>
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-5">
              {liveSlots.map((slot) => (
                <div key={slot.key} className="min-w-0">
                  <dt className="truncate text-[11px] font-semibold uppercase tracking-wide text-d-muted">
                    {slot.label}
                  </dt>
                  <dd
                    className={`mt-1 truncate text-lg font-bold ${
                      slot.unavailable ? 'text-d-muted' : 'text-gold-400'
                    }`}
                  >
                    {slot.kpi
                      ? formatKpiValue(
                          slot.kpi.current.numericValue,
                          slot.kpi.unit,
                          slot.kpi.numberFormat,
                        )
                      : 'Unavailable'}
                  </dd>
                  {slot.kpi && estimatedIds.has(slot.kpi.outputId) ? (
                    <p className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-sky-300">
                      Estimated
                    </p>
                  ) : null}
                  {slot.unavailableDetail ? (
                    <p
                      className="mt-1 line-clamp-2 text-[10px] text-amber-200"
                      title={slot.unavailableDetail}
                    >
                      {slot.unavailableDetail}
                    </p>
                  ) : null}
                </div>
              ))}
            </dl>
          </section>

          <section className="min-w-0 rounded-lg border border-d-border bg-d-card p-4 shadow-sm sm:col-span-2 lg:col-span-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-200">
              Assumptions
            </p>
            {assumptions.length > 0 ? (
              <dl className="mt-4 space-y-2.5">
                {assumptions.slice(0, 8).map((assumption) => (
                  <div
                    key={assumption.targetKey}
                    className="flex min-w-0 items-start justify-between gap-3 border-b border-d-border/70 pb-2 text-xs"
                  >
                    <dt className="min-w-0 flex-1 break-words text-d-muted">
                      {assumption.label}
                    </dt>
                    <dd className="shrink-0 font-mono font-semibold text-slate-200">
                      {formatAssumptionValue(assumption, overridesByTarget)}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="mt-3 text-sm text-d-muted">
                No editable numeric assumptions.
              </p>
            )}
            {assumptions.length > 8 ? (
              <p className="mt-3 text-xs text-d-muted">
                +{assumptions.length - 8} additional model assumptions
              </p>
            ) : null}
          </section>
        </aside>

        <main className="min-w-0 space-y-4">
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-2xl font-bold text-white">
                Sensitivity Analysis
              </h1>
              <p className="mt-1 text-sm text-d-muted">
                Fixed investment view · canonical model assumptions ·{' '}
                {irrSlot?.displayLabel ?? 'IRR unavailable'}
              </p>
              <p className="mt-1 truncate font-mono text-[10px] text-d-dim">
                run_id: {calculationRunId}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span
                aria-live="polite"
                className={`rounded px-3 py-1.5 text-xs font-semibold ${
                  recalculating
                    ? 'bg-amber-900/30 text-amber-200'
                    : errorMessage
                      ? 'bg-amber-900/30 text-amber-200'
                    : 'bg-green-900/30 text-green-300'
                }`}
              >
                {recalculating
                  ? 'Recalculating…'
                  : errorMessage
                    ? 'Last successful result retained'
                    : 'Persisted results'}
              </span>
              <button
                type="button"
                aria-label="Refresh persisted results"
                onClick={onRefresh}
                className="rounded border border-d-border px-3 py-1.5 text-xs text-white transition hover:border-gold-400 hover:bg-d-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400"
              >
                Refresh
              </button>
            </div>
          </header>

          <section
            aria-label="Fixed investment KPIs"
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"
          >
            {dashboard.slots.map((slot) => (
              <article
                key={slot.key}
                data-testid="fixed-kpi-card"
                className="min-w-0 rounded-lg border border-d-border bg-d-card p-4 shadow-sm"
              >
                <p className="min-h-8 text-xs font-semibold uppercase tracking-wide text-slate-200">
                  {slot.displayLabel}
                </p>
                <p
                  className={`mt-2 truncate text-2xl font-bold ${
                    slot.unavailable ? 'text-d-muted' : 'text-gold-400'
                  }`}
                >
                  {slot.kpi
                    ? formatKpiValue(
                        slot.kpi.current.numericValue,
                        slot.kpi.unit,
                        slot.kpi.numberFormat,
                      )
                    : 'Unavailable'}
                </p>
                <p className="mt-2 text-xs text-d-muted">
                  vs base:{' '}
                  <span className="font-mono text-slate-200">
                    {slot.kpi
                      ? formatKpiDelta(
                          slot.kpi.absoluteChange,
                          slot.kpi.unit,
                          slot.kpi.numberFormat,
                        )
                      : 'Unavailable'}
                  </span>
                </p>
                {slot.kpi && estimatedIds.has(slot.kpi.outputId) ? (
                  <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-sky-300">
                    Estimated
                  </p>
                ) : null}
                {slot.unavailableDetail ? (
                  <p
                    className="mt-2 line-clamp-2 text-[10px] leading-4 text-amber-200"
                    title={slot.unavailableDetail}
                  >
                    {slot.unavailableDetail}
                  </p>
                ) : null}
              </article>
            ))}
          </section>

          <div className="grid min-w-0 gap-4 2xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
            <section
              data-testid="fixed-sensitivity-assumption-card"
              className="flex h-[38rem] min-w-0 flex-col rounded-lg border border-d-border bg-d-card p-4 shadow-sm"
            >
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-white">
                    Assumption sliders
                  </h2>
                  <p className="mt-1 text-xs text-d-muted">
                    Drag for an Estimated preview — one exact current run starts
                    after 400ms
                  </p>
                </div>
              </div>
              <fieldset
                disabled={controlsDisabled}
                data-testid="fixed-sensitivity-controls"
                className="flex min-h-0 min-w-0 flex-1 flex-col disabled:cursor-not-allowed disabled:opacity-70"
              >
                <legend className="sr-only">
                  Editable canonical assumptions
                </legend>
                <div
                  ref={assumptionScrollRef}
                  data-testid="fixed-sensitivity-assumption-scroll-region"
                  className="min-h-0 flex-1 overflow-y-auto pr-1"
                >
                  <SensitivityAssumptionPanel
                    assumptions={visibleAssumptions}
                    overridesByTarget={overridesByTarget}
                    onValueChange={onValueChange}
                    onReset={onReset}
                    onResetAll={onResetAll}
                  />
                </div>
                {assumptions.length > 8 ? (
                  <button
                    type="button"
                    aria-label={
                      expanded
                        ? 'Show first 8 assumptions'
                        : `Show all ${assumptions.length} assumptions`
                    }
                    onClick={onToggleExpanded}
                    className="mt-4 w-full shrink-0 rounded border border-d-border px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-gold-400 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400"
                  >
                    {expanded ? 'Show first 8' : `Show all ${assumptions.length}`}
                  </button>
                ) : null}
              </fieldset>
            </section>

            <section className="flex h-[38rem] min-w-0 flex-col rounded-lg border border-d-border bg-d-card p-4 shadow-sm">
              <div className="flex shrink-0 flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-white">
                    IRR tornado chart
                  </h2>
                  <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-d-muted">
                    Ranked by impact · {analysisOutputLabel}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {initialAnalysisStatus ? (
                    <span
                      aria-live="polite"
                      className="text-[11px] text-d-muted"
                    >
                      {initialAnalysisStatus}
                    </span>
                  ) : null}
                  {analysisStale ? (
                    <span className="rounded border border-amber-700/60 bg-amber-900/20 px-2 py-1 text-[11px] text-amber-200">
                      Out of date
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={onRunAnalysis}
                    disabled={analysisDisabled}
                    className="rounded border border-d-border px-2 py-1 text-[11px] text-slate-200 transition hover:border-gold-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {analysisButtonLabel}
                  </button>
                </div>
              </div>
              <div className="mt-4 grid min-h-0 flex-1 gap-3 lg:grid-cols-[12rem_minmax(0,1fr)]">
                <aside
                  aria-label="Tornado drivers"
                  className="flex min-h-0 flex-col rounded border border-d-border bg-d-panel/40 p-2"
                >
                  <div className="mb-2 flex items-center justify-between gap-2 px-1">
                    <p className="text-xs font-semibold text-slate-200">
                      Drivers
                    </p>
                    <span className="text-[11px] text-d-muted">
                      {tornadoDriverKeys.length}/{DEFAULT_TORNADO_DRIVER_LIMIT}
                    </span>
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                    <ul className="space-y-1">
                      {eligibleTornadoDrivers.map((assumption) => {
                        const selected = selectedTornadoDrivers.has(
                          assumption.targetKey,
                        );
                        return (
                          <li key={assumption.targetKey}>
                            <button
                              type="button"
                              aria-pressed={selected}
                              disabled={controlsDisabled}
                              onClick={() =>
                                onTornadoDriverToggle(assumption.targetKey)
                              }
                              className={`w-full rounded px-2 py-1.5 text-left text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400 disabled:cursor-not-allowed disabled:opacity-50 ${
                                selected
                                  ? 'bg-gold-500/20 text-gold-200'
                                  : 'text-d-muted hover:bg-d-hover hover:text-slate-100'
                              }`}
                            >
                              <span className="block truncate">
                                {assumption.label}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                  {pendingReplacementDriver ? (
                    <div className="mt-2 rounded border border-gold-500/40 bg-gold-500/10 p-2">
                      <p className="text-[11px] leading-4 text-gold-100">
                        Replace with {pendingReplacementDriver.label}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {tornadoDriverKeys.map((targetKey) => {
                          const assumption = eligibleTornadoDrivers.find(
                            (candidate) => candidate.targetKey === targetKey,
                          );
                          return (
                            <button
                              key={targetKey}
                              type="button"
                              onClick={() => onTornadoDriverReplace(targetKey)}
                              className="rounded border border-gold-400/50 px-1.5 py-1 text-[10px] text-gold-100 hover:bg-gold-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400"
                            >
                              {assumption?.label ?? targetKey}
                            </button>
                          );
                        })}
                        <button
                          type="button"
                          onClick={onCancelTornadoDriverReplacement}
                          className="rounded border border-d-border px-1.5 py-1 text-[10px] text-d-muted hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                </aside>
                <div className="min-h-0 overflow-y-auto pr-1">
                  {analysisUnavailableReason ? (
                    <p className="rounded border border-amber-800/50 bg-amber-900/10 p-4 text-sm text-amber-100">
                      {analysisUnavailableReason}
                    </p>
                  ) : (
                    <SensitivityTornadoChart
                      rows={tornadoRows}
                      outputLabel={analysisOutputLabel}
                      formatValue={formatAnalyzedOutputValue}
                      formatDelta={formatAnalyzedOutputDelta}
                    />
                  )}
                </div>
              </div>
            </section>
          </div>

          <div className="grid min-w-0 gap-4 xl:grid-cols-2">
            <section className="min-w-0 overflow-x-auto rounded-lg border border-d-border bg-d-card p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-white">
                  Scenario comparison
                </h2>
                <span className="text-[11px] text-d-muted">
                  base vs current
                </span>
              </div>
              <table className="mt-4 w-full min-w-[30rem] text-sm">
                <thead>
                  <tr className="border-b border-d-border text-xs uppercase tracking-wide text-d-muted">
                    <th className="pb-2 text-left font-medium">Metric</th>
                    <th className="pb-2 text-right font-medium">Base</th>
                    <th className="pb-2 text-right font-medium">Scenario</th>
                    <th className="pb-2 text-right font-medium">Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {dashboard.slots.map((slot) => (
                    <tr key={slot.key} className="border-b border-d-border">
                      <th scope="row" className="py-3 text-left font-medium text-white">
                        {slot.displayLabel}
                      </th>
                      <td className="py-3 text-right font-mono text-slate-300">
                        {slot.kpi
                          ? formatKpiValue(
                              slot.kpi.baseline.numericValue,
                              slot.kpi.unit,
                              slot.kpi.numberFormat,
                            )
                          : 'Unavailable'}
                      </td>
                      <td className="py-3 text-right font-mono font-semibold text-white">
                        {slot.kpi
                          ? formatKpiValue(
                              slot.kpi.current.numericValue,
                              slot.kpi.unit,
                              slot.kpi.numberFormat,
                            )
                          : 'Unavailable'}
                      </td>
                      <td className="py-3 text-right font-mono text-gold-300">
                        {slot.kpi
                          ? formatKpiDelta(
                              slot.kpi.absoluteChange,
                              slot.kpi.unit,
                              slot.kpi.numberFormat,
                            )
                          : 'Unavailable'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="min-w-0 rounded-lg border border-d-border bg-d-card p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-white">
                  Two-way sensitivity
                </h2>
                <div className="flex items-center gap-2">
                  {analysisStale ? (
                    <span className="rounded border border-amber-700/60 bg-amber-900/20 px-2 py-1 text-[11px] text-amber-200">
                      Out of date
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={onRunAnalysis}
                    disabled={analysisDisabled}
                    className="rounded border border-d-border px-2 py-1 text-[11px] text-slate-200 transition hover:border-gold-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {analysisButtonLabel}
                  </button>
                </div>
              </div>
              <div className="mt-4">
                {analysisUnavailableReason ? (
                  <p className="rounded border border-amber-800/50 bg-amber-900/10 p-4 text-sm text-amber-100">
                    {analysisUnavailableReason}
                  </p>
                ) : (
                  <SensitivityTwoWayMatrix
                    matrix={matrix}
                    outputLabel={analysisOutputLabel}
                    unavailableReason={twoWayUnavailableReason}
                    formatAxisValue={formatAxisValue}
                    formatOutputValue={formatAnalyzedOutputValue}
                  />
                )}
              </div>
            </section>
          </div>

          <section className="min-w-0 rounded-lg border border-d-border bg-d-card p-4 shadow-sm">
            <h2 className="text-base font-semibold text-white">
              Current Assumptions
            </h2>
            {assumptions.length > 0 ? (
              <dl className="mt-4 grid gap-x-8 gap-y-2 sm:grid-cols-2 xl:grid-cols-4">
                {assumptions.map((assumption) => (
                  <div
                    key={assumption.targetKey}
                    className="flex min-w-0 items-start justify-between gap-3 border-b border-d-border py-2 text-xs"
                  >
                    <dt className="min-w-0 flex-1 break-words text-slate-200">
                      {assumption.label}
                    </dt>
                    <dd className="shrink-0 font-mono font-semibold text-white">
                      {formatAssumptionValue(assumption, overridesByTarget)}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="mt-3 text-sm text-d-muted">
                No editable numeric assumptions.
              </p>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
