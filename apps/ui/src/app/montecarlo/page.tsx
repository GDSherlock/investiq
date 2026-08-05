'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useActiveAnalysis } from '../ActiveAnalysisContext';
import FloatingAssistant from '../FloatingAssistant';
import AnalysisStatusSidebar from '@/components/analysis/AnalysisStatusSidebar';
import { MonteCarloCorrelationDialog } from '@/components/monte-carlo/MonteCarloCorrelationDialog';
import {
  cancelMonteCarloRun,
  createMonteCarloRun,
  getModelDiagnostics,
  getMonteCarloInputs,
  getMonteCarloRun,
  getMonteCarloRunHistory,
  getOverviewAnalysis,
} from '@/lib/api';
import type {
  ModelDiagnosticsResponse,
  MonteCarloConfiguredInput,
  MonteCarloDistributionType,
  MonteCarloEligibleInput,
  MonteCarloInputCatalogResponse,
  MonteCarloMetricResult,
  MonteCarloOutputRole,
  MonteCarloRunResponse,
  OverviewAnalysisResponse,
} from '@/lib/calculation-api-types';
import { defaultMonteCarloSpread } from '@/lib/monte-carlo-defaults';
import { formatUiNumber } from '@/lib/ui-number-format';

const RUN_STATUSES = [
  'queued',
  'running',
  'completed',
  'failed',
  'cancelled',
] as const;

const DISTRIBUTION_TYPES: MonteCarloDistributionType[] = [
  'normal',
  'triangular',
  'uniform',
  'lognormal',
  'discrete',
];

type DraftInput = {
  selected: boolean;
  distributionType: MonteCarloDistributionType;
  parameters: Record<string, string>;
};

function numeric(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Invalid numeric value: ${value}`);
  }
  return parsed;
}

function defaultParameters(
  input: MonteCarloEligibleInput,
  distributionType: MonteCarloDistributionType = 'normal',
): Record<string, string> {
  const current = numeric(input.current_value);
  const spread = defaultMonteCarloSpread(current);
  if (distributionType === 'triangular') {
    return {
      low: String(current - spread),
      mode: String(current),
      high: String(current + spread),
    };
  }
  if (distributionType === 'uniform') {
    return {
      low: String(current - spread),
      high: String(current + spread),
    };
  }
  if (distributionType === 'lognormal') {
    return {
      log_mean: String(Math.log(Math.max(Math.abs(current), 0.000001))),
      log_stddev: '0.1',
    };
  }
  if (distributionType === 'discrete') {
    return {
      values: `${current - spread}, ${current}, ${current + spread}`,
      probabilities: '0.25, 0.5, 0.25',
    };
  }
  return {
    mean: String(current),
    stddev: String(spread),
  };
}

function makeDrafts(
  inputs: MonteCarloEligibleInput[],
): Record<string, DraftInput> {
  return Object.fromEntries(
    inputs.map((input) => [
      input.parameter_id,
      {
        selected: true,
        distributionType: 'normal',
        parameters: defaultParameters(input),
      },
    ]),
  );
}

function identityMatrix(size: number): number[][] {
  return Array.from({ length: size }, (_, row) =>
    Array.from({ length: size }, (__, column) =>
      row === column ? 1 : 0,
    ),
  );
}

function distributionParameters(
  draft: DraftInput,
): Record<string, unknown> {
  if (draft.distributionType === 'discrete') {
    const values = draft.parameters.values
      .split(',')
      .map((value) => numeric(value.trim()));
    const probabilities = draft.parameters.probabilities
      .split(',')
      .map((value) => numeric(value.trim()));
    if (
      values.length === 0 ||
      values.length !== probabilities.length
    ) {
      throw new Error(
        'Discrete values and probabilities must have equal lengths.',
      );
    }
    return { values, probabilities };
  }
  return Object.fromEntries(
    Object.entries(draft.parameters).map(([key, value]) => [
      key,
      numeric(value),
    ]),
  );
}

function formatMetricValue(
  role: MonteCarloOutputRole,
  value: number | undefined,
): string {
  if (value === undefined || !Number.isFinite(value)) {
    return 'Unavailable';
  }
  if (role.endsWith('_irr')) {
    return `${formatUiNumber(value * 100, {
      maximumFractionDigits: 2,
    })}%`;
  }
  if (role === 'minimum_dscr') {
    return `${formatUiNumber(value, {
      maximumFractionDigits: 2,
    })}x`;
  }
  return formatUiNumber(value, {
    locales: 'en',
    notation: 'compact',
    maximumFractionDigits: 2,
  });
}

function formatProbability(value: number): string {
  return `${formatUiNumber(value * 100, {
    maximumFractionDigits: 1,
  })}%`;
}

function ParameterFields({
  input,
  draft,
  onChange,
}: {
  input: MonteCarloEligibleInput;
  draft: DraftInput;
  onChange: (next: DraftInput) => void;
}) {
  const updateParameter = (key: string, value: string) => {
    onChange({
      ...draft,
      parameters: { ...draft.parameters, [key]: value },
    });
  };
  const fields =
    draft.distributionType === 'normal'
      ? [
          ['mean', 'Mean'],
          ['stddev', 'Std dev'],
        ]
      : draft.distributionType === 'triangular'
        ? [
            ['low', 'Low'],
            ['mode', 'Mode'],
            ['high', 'High'],
          ]
        : draft.distributionType === 'uniform'
          ? [
              ['low', 'Low'],
              ['high', 'High'],
            ]
          : draft.distributionType === 'lognormal'
            ? [
                ['log_mean', 'Log mean'],
                ['log_stddev', 'Log std dev'],
              ]
            : [
                ['values', 'Values'],
                ['probabilities', 'Probabilities'],
              ];

  return (
    <div className="grid grid-cols-2 gap-2 mt-3">
      {fields.map(([key, label]) => (
        <label key={key} className="min-w-0 text-[9px] text-d-muted">
          {label}
          <input
            type={draft.distributionType === 'discrete' ? 'text' : 'number'}
            step="any"
            value={draft.parameters[key] ?? ''}
            onChange={(event) =>
              updateParameter(key, event.target.value)
            }
            aria-label={`${input.label} ${label}`}
            className="mt-1 w-full rounded border border-d-border bg-d-bg px-2 py-1.5 text-xs text-white"
          />
        </label>
      ))}
    </div>
  );
}

function MetricCard({
  metric,
  run,
  persistedStatus,
}: {
  metric: MonteCarloMetricResult;
  run: MonteCarloRunResponse | null;
  persistedStatus: string;
}) {
  if (
    metric.availability_status !== 'available' ||
    metric.percentiles === null
  ) {
    return (
      <section className="flex h-full min-h-[29rem] flex-col rounded-lg border border-d-border bg-d-card p-6">
        <div className="text-[10px] uppercase tracking-wider text-d-muted">
          {metric.label}
        </div>
        <div className="mt-3 text-lg font-semibold text-d-muted">
          Unavailable
        </div>
        <p className="mt-1 text-[9px] text-d-muted">
          {metric.unavailable_reason}
        </p>
      </section>
    );
  }
  const { p10, p50, p90 } = metric.percentiles;
  const percentileSpan = p90 - p10;
  const p50Position =
    Number.isFinite(percentileSpan) && percentileSpan > 0
      ? Math.min(
          100,
          Math.max(0, ((p50 - p10) / percentileSpan) * 100),
        )
      : 50;
  return (
    <section className="flex h-full min-h-[29rem] flex-col rounded-lg border border-d-border bg-d-card p-6">
      <div className="text-[11px] uppercase tracking-wider text-d-muted">
        {metric.label}
      </div>
      <div className="mt-8 flex items-end gap-3">
        <div className="pb-1 text-[10px] uppercase tracking-wider text-d-muted">
          P50 median
        </div>
        <div className="text-5xl font-bold leading-none text-gold-400">
          {formatMetricValue(metric.role, p50)}
        </div>
      </div>
      <div
        className="mt-8 border-t border-d-border pt-4"
        aria-label="P10 to P90 percentile range"
      >
        <div className="relative h-2 rounded-full bg-d-border">
          <div className="absolute inset-0 rounded-full bg-gold-500/20" />
          <span
            className="absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gold-400"
            style={{ left: `${p50Position}%` }}
          />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4">
          <div>
            <div className="text-[10px] uppercase text-d-muted">P10</div>
            <div className="mt-1 text-xl font-semibold text-white">
              {formatMetricValue(metric.role, p10)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase text-d-muted">P90</div>
            <div className="mt-1 text-xl font-semibold text-white">
              {formatMetricValue(metric.role, p90)}
            </div>
          </div>
        </div>
      </div>
      {Object.entries(metric.probabilities).map(([label, value]) => (
        <div
          key={label}
          className="mt-3 flex justify-between gap-3 border-t border-d-border pt-2 text-[11px]"
        >
          <span className="text-d-muted">
            {label.replaceAll('_', ' ')}
          </span>
          <span className="text-emerald-400">
            {formatProbability(value)}
          </span>
        </div>
      ))}
      <div className="mt-auto pt-8 text-[10px] leading-5 text-d-muted">
        <div>
          {persistedStatus === 'completed' ? 'Completed' : persistedStatus}
          {' · '}
          {formatUiNumber(run?.trial_count, {
            maximumFractionDigits: 0,
            fallback: '—',
          })}{' '}
          trials
        </div>
        {run && (
          <div>
            Run {run.monte_carlo_run_id.slice(0, 8)}
            {run.runtime_ms !== null && (
              <>
                {' · '}
                {formatUiNumber(run.runtime_ms / 1000, {
                  maximumFractionDigits: 2,
                })}{' '}
                sec
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function DistributionChart({
  metric,
}: {
  metric: MonteCarloMetricResult;
}) {
  const rows =
    metric.distribution?.bins.map((bin) => ({
      bucket: `${formatUiNumber(bin.lower)}–${formatUiNumber(bin.upper)}`,
      count: bin.count,
    })) ?? [];
  return (
    <section className="h-full min-h-[29rem] min-w-0 rounded-lg border border-d-border bg-d-card p-6">
      <h2 className="text-base font-semibold text-white">
        {metric.label} distribution
      </h2>
      <p className="mt-1 text-[11px] text-d-muted">
        Persisted bounded histogram · no per-trial calculation runs
      </p>
      {rows.length === 0 ? (
        <div className="flex h-60 items-center justify-center text-sm text-d-muted">
          Unavailable
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={360}>
          <BarChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
            <XAxis
              dataKey="bucket"
              interval="preserveStartEnd"
              tick={{ fontSize: 10 }}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              tickFormatter={(value: number) =>
                formatUiNumber(value, {
                  maximumFractionDigits: 0,
                })
              }
            />
            <Tooltip
              contentStyle={{
                fontSize: 12,
                backgroundColor: '#111C44',
                border: '1px solid #1B2B65',
              }}
              formatter={(value: number, name: string) => [
                formatUiNumber(value, {
                  maximumFractionDigits: 0,
                }),
                name,
              ]}
            />
            <Bar dataKey="count" fill="#60a5fa" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}

export default function MonteCarloPage() {
  const analysis = useActiveAnalysis();
  const requestRevision = useRef(0);
  const sidebarRequestRevision = useRef(0);
  const [catalog, setCatalog] =
    useState<MonteCarloInputCatalogResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftInput>>(
    {},
  );
  const [correlations, setCorrelations] = useState<number[][]>([]);
  const [trialCount, setTrialCount] = useState(50000);
  const [randomSeed, setRandomSeed] = useState(1729);
  const [run, setRun] = useState<MonteCarloRunResponse | null>(null);
  const [overview, setOverview] =
    useState<OverviewAnalysisResponse | null>(null);
  const [diagnostics, setDiagnostics] =
    useState<ModelDiagnosticsResponse | null>(null);
  const [correlationDialogOpen, setCorrelationDialogOpen] =
    useState(false);
  const [inputQuery, setInputQuery] = useState('');
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const revision = ++requestRevision.current;
    if (
      analysis.status !== 'ready' ||
      analysis.modelVersionId === null ||
      analysis.activeRunId === null
    ) {
      setCatalog(null);
      setRun(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([
      getMonteCarloInputs(analysis.modelVersionId),
      getMonteCarloRunHistory(analysis.modelVersionId),
    ])
      .then(([nextCatalog, history]) => {
        if (
          revision !== requestRevision.current ||
          nextCatalog.model_version_id !== analysis.modelVersionId
        ) {
          return;
        }
        setCatalog(nextCatalog);
        setDrafts(makeDrafts(nextCatalog.inputs));
        setCorrelations(identityMatrix(nextCatalog.inputs.length));
        setRun(
          history.runs.find(
            (candidate) =>
              candidate.current_calculation_run_id ===
              analysis.activeRunId,
          ) ?? null,
        );
      })
      .catch((caught) => {
        if (revision === requestRevision.current) {
          setError(
            caught instanceof Error
              ? caught
              : new Error('Unable to load Monte Carlo configuration.'),
          );
        }
      })
      .finally(() => {
        if (revision === requestRevision.current) {
          setLoading(false);
        }
      });
  }, [
    analysis.activeRunId,
    analysis.modelVersionId,
    analysis.status,
  ]);

  useEffect(() => {
    const revision = ++sidebarRequestRevision.current;
    if (
      analysis.status !== 'ready' ||
      analysis.modelVersionId === null ||
      analysis.activeRunId === null
    ) {
      setOverview(null);
      setDiagnostics(null);
      return;
    }

    const modelVersionId = analysis.modelVersionId;
    const activeRunId = analysis.activeRunId;
    void Promise.allSettled([
      getOverviewAnalysis(activeRunId),
      getModelDiagnostics(modelVersionId),
    ]).then(([overviewResult, diagnosticsResult]) => {
      if (revision !== sidebarRequestRevision.current) {
        return;
      }
      setOverview(
        overviewResult.status === 'fulfilled' &&
          overviewResult.value.calculation_run_id === activeRunId
          ? overviewResult.value
          : null,
      );
      setDiagnostics(
        diagnosticsResult.status === 'fulfilled' &&
          diagnosticsResult.value.model_version_id === modelVersionId
          ? diagnosticsResult.value
          : null,
      );
    });
  }, [
    analysis.activeRunId,
    analysis.modelVersionId,
    analysis.status,
  ]);

  useEffect(() => {
    if (run === null || !['queued', 'running'].includes(run.status)) {
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      getMonteCarloRun(run.monte_carlo_run_id)
        .then((next) => {
          if (active) {
            setRun(next);
          }
        })
        .catch((caught) => {
          if (active) {
            setError(
              caught instanceof Error
                ? caught
                : new Error('Unable to refresh the simulation run.'),
            );
          }
        });
    }, 1000);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [run]);

  useEffect(
    () => () => {
      requestRevision.current += 1;
      sidebarRequestRevision.current += 1;
    },
    [],
  );

  const selectedInputs = useMemo(
    () =>
      catalog?.inputs.filter(
        (input) => drafts[input.parameter_id]?.selected,
      ) ?? [],
    [catalog, drafts],
  );
  const visibleInputs = useMemo(() => {
    const normalizedQuery = inputQuery.trim().toLowerCase();
    return (
      catalog?.inputs.filter((input) => {
        const draft = drafts[input.parameter_id];
        if (showSelectedOnly && !draft?.selected) {
          return false;
        }
        if (normalizedQuery.length === 0) {
          return true;
        }
        return [input.label, input.business_role, input.unit]
          .filter(Boolean)
          .some((value) =>
            String(value).toLowerCase().includes(normalizedQuery),
          );
      }) ?? []
    );
  }, [catalog, drafts, inputQuery, showSelectedOnly]);

  const setAllInputsSelected = (selected: boolean) => {
    setDrafts((current) =>
      Object.fromEntries(
        Object.entries(current).map(([parameterId, draft]) => [
          parameterId,
          { ...draft, selected },
        ]),
      ),
    );
  };

  const handleDistributionChange = (
    input: MonteCarloEligibleInput,
    distributionType: MonteCarloDistributionType,
  ) => {
    setDrafts((current) => ({
      ...current,
      [input.parameter_id]: {
        selected: current[input.parameter_id]?.selected ?? true,
        distributionType,
        parameters: defaultParameters(input, distributionType),
      },
    }));
  };

  const updateCorrelation = (
    row: number,
    column: number,
    value: string,
  ) => {
    const parsed = Number(value);
    setCorrelations((current) =>
      current.map((values, rowIndex) =>
        values.map((existing, columnIndex) => {
          if (rowIndex === row && columnIndex === column) {
            return parsed;
          }
          if (rowIndex === column && columnIndex === row) {
            return parsed;
          }
          return existing;
        }),
      ),
    );
  };

  const handleRun = async () => {
    if (
      catalog === null ||
      analysis.modelVersionId === null ||
      analysis.graphVersionId === null ||
      analysis.baselineRunId === null ||
      analysis.activeRunId === null
    ) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      if (selectedInputs.length === 0) {
        throw new Error('Select at least one stochastic input.');
      }
      if (!catalog.supported_output_roles.includes('project_irr')) {
        throw new Error('Project IRR is unavailable for this model.');
      }
      const inputIndices = selectedInputs.map((input) =>
        catalog.inputs.findIndex(
          (candidate) =>
            candidate.parameter_id === input.parameter_id,
        ),
      );
      const inputs: MonteCarloConfiguredInput[] = selectedInputs.map(
        (input) => {
          const draft = drafts[input.parameter_id];
          if (!draft) {
            throw new Error(`Missing configuration for ${input.label}.`);
          }
          return {
            parameter_id: input.parameter_id,
            distribution_type: draft.distributionType,
            distribution_parameters: distributionParameters(draft),
          };
        },
      );
      const next = await createMonteCarloRun(
        analysis.modelVersionId,
        {
          graph_version_id: analysis.graphVersionId,
          baseline_calculation_run_id: analysis.baselineRunId,
          current_calculation_run_id: analysis.activeRunId,
          trial_count: Math.min(50000, Math.max(1, trialCount)),
          random_seed: randomSeed,
          inputs,
          correlation_matrix: inputIndices.map((row) =>
            inputIndices.map((column) => correlations[row][column]),
          ),
          selected_output_roles: ['project_irr'],
          idempotency_key: crypto.randomUUID(),
        },
      );
      setRun(next);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught
          : new Error('Unable to queue the simulation.'),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (run === null) {
      return;
    }
    setError(null);
    try {
      setRun(await cancelMonteCarloRun(run.monte_carlo_run_id));
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught
          : new Error('Unable to cancel the simulation.'),
      );
    }
  };

  const metrics = run?.result_artifact?.metrics ?? [];
  const rankingMetric =
    metrics.find((metric) => metric.rankings.length > 0) ?? null;
  const persistedStatus =
    run !== null && RUN_STATUSES.includes(run.status)
      ? run.status
      : 'Unavailable';
  const canConfigure =
    analysis.status === 'ready' && catalog !== null && !loading;
  const projectIrrAvailable =
    catalog?.supported_output_roles.includes('project_irr') ?? false;
  const projectIrrKpis = useMemo(
    () =>
      overview?.kpis
        .filter((kpi) => kpi.role === 'project_irr')
        .slice(0, 1) ?? [],
    [overview],
  );

  return (
    <div className="flex flex-col gap-4 lg:relative lg:left-1/2 lg:w-[calc(100vw-2rem)] lg:-translate-x-1/2 lg:flex-row lg:gap-6">
      <AnalysisStatusSidebar
        analysis={analysis}
        kpis={projectIrrKpis}
        diagnostics={diagnostics}
        featuredKpi
        wide
      />

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <section className="min-h-[6.75rem] rounded-lg border border-d-border bg-d-card p-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h1 className="text-lg font-semibold text-white">
                Monte Carlo simulation engine
              </h1>
              <p className="mt-1 text-xs text-d-muted">
                Dynamic canonical inputs · calibrated model · persisted
                asynchronous results
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-[10px] text-d-muted">
                Trials
                <input
                  type="number"
                  min={1}
                  max={50000}
                  value={trialCount}
                  onChange={(event) =>
                    setTrialCount(Number(event.target.value))
                  }
                  className="ml-2 w-24 rounded border border-d-border bg-d-bg px-2 py-1.5 text-xs text-white"
                />
              </label>
              <label className="text-[10px] text-d-muted">
                Seed
                <input
                  type="number"
                  value={randomSeed}
                  onChange={(event) =>
                    setRandomSeed(Number(event.target.value))
                  }
                  className="ml-2 w-24 rounded border border-d-border bg-d-bg px-2 py-1.5 text-xs text-white"
                />
              </label>
              <button
                type="button"
                disabled={!canConfigure || !projectIrrAvailable || submitting}
                onClick={() => void handleRun()}
                className="rounded-lg bg-gold-500 px-5 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {submitting ? 'Queueing…' : 'Run Monte Carlo'}
              </button>
              {run && ['queued', 'running'].includes(run.status) && (
                <button
                  type="button"
                  onClick={() => void handleCancel()}
                  className="rounded-lg border border-red-500/50 px-4 py-2 text-xs text-red-300"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
        </section>

        {analysis.status !== 'ready' && (
          <section className="rounded-lg border border-d-border bg-d-card p-8 text-center">
            <p className="text-sm text-d-muted">
              A persisted calculation run is required.
            </p>
            <Link
              href="/"
              className="mt-3 inline-flex text-xs text-gold-400 hover:underline"
            >
              Open calculation setup
            </Link>
          </section>
        )}

        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-950/30 p-4 text-sm text-red-300">
            {error.message}
          </div>
        )}

        {canConfigure && catalog && (
          <div className="grid grid-cols-1 items-stretch gap-4 xl:grid-cols-[minmax(360px,0.48fr)_minmax(0,1fr)]">
            <section className="flex h-[calc(100vh-12rem)] min-h-[36rem] min-w-0 flex-col rounded-lg border border-d-border bg-d-card p-4 xl:h-0 xl:min-h-full">
              <header className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-white">
                    Stochastic inputs
                  </h2>
                  <p className="mt-1 text-[10px] text-d-muted">
                    {selectedInputs.length} of {catalog.inputs.length} selected
                    · scroll to configure
                  </p>
                </div>
                <button
                  type="button"
                  disabled={selectedInputs.length === 0}
                  onClick={() => setAllInputsSelected(false)}
                  className="text-[10px] font-medium text-gold-400 transition hover:text-gold-300 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Clear all
                </button>
              </header>
              <div className="mt-4 flex gap-2 border-b border-d-border pb-4">
                <input
                  type="search"
                  value={inputQuery}
                  onChange={(event) => setInputQuery(event.target.value)}
                  placeholder="Search inputs"
                  aria-label="Search inputs"
                  className="min-w-0 flex-1 rounded-lg border border-d-border bg-d-bg px-3 py-2 text-xs text-white placeholder:text-d-muted focus:border-gold-400 focus:outline-none"
                />
                <button
                  type="button"
                  aria-pressed={showSelectedOnly}
                  onClick={() => setShowSelectedOnly((current) => !current)}
                  className="rounded-lg border border-d-border px-3 py-2 text-[10px] font-medium text-d-muted transition hover:border-gold-500/70 hover:text-white aria-pressed:border-gold-500 aria-pressed:text-gold-400"
                >
                  Selected
                </button>
              </div>
              <div className="mt-4 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1 [scrollbar-gutter:stable]">
                {catalog.inputs.length === 0 && (
                  <div className="rounded-lg border border-d-border bg-d-bg/40 p-5 text-xs text-d-muted">
                    No editable stochastic-eligible canonical parameters
                    are available.
                  </div>
                )}
                {catalog.inputs.length > 0 && visibleInputs.length === 0 && (
                  <div className="rounded-lg border border-d-border bg-d-bg/40 p-5 text-xs text-d-muted">
                    No inputs match the current filter.
                  </div>
                )}
                {visibleInputs.map((input) => {
                  const draft = drafts[input.parameter_id];
                  if (!draft) {
                    return null;
                  }
                  return (
                    <section
                      key={input.parameter_id}
                      className="rounded-lg border border-d-border bg-d-bg/40 p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <label className="flex min-w-0 items-start gap-2">
                          <input
                            type="checkbox"
                            checked={draft.selected}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [input.parameter_id]: {
                                  ...draft,
                                  selected: event.target.checked,
                                },
                              }))
                            }
                            className="mt-0.5 accent-gold-500"
                          />
                          <span>
                            <span className="block text-xs font-semibold text-white">
                              {input.label}
                            </span>
                            <span className="mt-0.5 block text-[9px] text-d-muted">
                              {input.business_role ?? 'Unclassified'} ·
                              current{' '}
                              {formatUiNumber(input.current_value, {
                                fallback: input.current_value,
                              })}{' '}
                              {input.unit ?? ''}
                            </span>
                          </span>
                        </label>
                        <select
                          value={draft.distributionType}
                          onChange={(event) =>
                            handleDistributionChange(
                              input,
                              event.target
                                .value as MonteCarloDistributionType,
                            )
                          }
                          className="rounded border border-d-border bg-d-bg px-2 py-1 text-[9px] uppercase text-emerald-400"
                        >
                          {DISTRIBUTION_TYPES.map((distribution) => (
                            <option key={distribution} value={distribution}>
                              {distribution}
                            </option>
                          ))}
                        </select>
                      </div>
                      {draft.selected && (
                        <ParameterFields
                          input={input}
                          draft={draft}
                          onChange={(next) =>
                            setDrafts((current) => ({
                              ...current,
                              [input.parameter_id]: next,
                            }))
                          }
                        />
                      )}
                    </section>
                  );
                })}
              </div>
            </section>

            <div className="grid min-w-0 grid-cols-1 items-stretch gap-4 xl:grid-cols-[minmax(300px,0.8fr)_minmax(0,1.2fr)]">
              <section className="min-h-40 rounded-lg border border-d-border bg-d-card p-5">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-d-muted">
                  Target output
                </div>
                <div className="mt-5 text-3xl font-bold text-gold-400">
                  Project IRR
                </div>
                <p className="mt-1 text-[10px] text-d-muted">
                  Fixed for comparable persisted simulations
                </p>
                {!projectIrrAvailable && (
                  <p className="mt-2 text-[10px] text-amber-300">
                    Project IRR is unavailable for this model.
                  </p>
                )}
              </section>

              <section className="min-h-40 rounded-lg border border-d-border bg-d-card p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-base font-semibold text-white">
                      Correlation matrix
                    </h2>
                    <p className="mt-1 max-w-sm text-[10px] text-d-muted">
                      Configure relationships without occupying the main
                      workspace.
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={selectedInputs.length < 2}
                    onClick={() => setCorrelationDialogOpen(true)}
                    className="rounded-lg border border-d-border px-4 py-2 text-xs font-semibold text-white transition hover:border-gold-500/70 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Open full matrix
                  </button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-[9px] text-d-muted">
                  <span className="rounded-full border border-d-border px-3 py-1">
                    {selectedInputs.length} inputs
                  </span>
                  <span className="rounded-full border border-d-border px-3 py-1">
                    Symmetric draft
                  </span>
                </div>
              </section>

              {metrics.map((metric) => (
                <Fragment key={metric.role}>
                  <div className="min-w-0">
                    <MetricCard
                      metric={metric}
                      run={run}
                      persistedStatus={persistedStatus}
                    />
                  </div>
                  <div className="min-w-0">
                    <DistributionChart metric={metric} />
                  </div>
                </Fragment>
              ))}

              {metrics.length === 0 && (
                <section className="flex min-h-44 items-center justify-center rounded-lg border border-d-border bg-d-card p-6 text-center xl:col-span-2">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-d-muted">
                      Persisted run status
                    </div>
                    <div className="mt-2 text-lg font-semibold text-white">
                      {persistedStatus}
                    </div>
                    {run?.error_message && (
                      <p className="mt-3 text-xs text-red-300">
                        {run.error_code}: {run.error_message}
                      </p>
                    )}
                  </div>
                </section>
              )}

              <section className="rounded-lg border border-d-border bg-d-card p-5 xl:col-span-2">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold text-white">
                      Sensitivity ranking
                    </h2>
                    <p className="mt-1 text-[10px] text-d-muted">
                      Top drivers shown · scroll for all selected inputs
                    </p>
                  </div>
                  <span className="rounded-full border border-d-border px-3 py-1 text-[9px] text-d-muted">
                    Contribution to Project IRR
                  </span>
                </div>
                {rankingMetric === null ? (
                  <div className="flex h-28 items-center justify-center text-xs text-d-muted">
                    Unavailable
                  </div>
                ) : (
                  <div className="mt-4 flex max-h-80 flex-col overflow-y-auto pr-2 [scrollbar-gutter:stable]">
                    {rankingMetric.rankings.map((ranking) => (
                      <div
                        key={ranking.parameter_id}
                        className="grid items-center gap-3 border-b border-d-border py-3 last:border-b-0 xl:grid-cols-[minmax(180px,0.8fr)_minmax(220px,1fr)_auto]"
                      >
                        <span className="text-[10px] font-medium text-white">
                          {ranking.label}
                        </span>
                        <div className="h-1.5 overflow-hidden rounded bg-d-bg">
                          <div
                            className="h-full rounded bg-gold-500"
                            style={{
                              width: `${Math.min(
                                100,
                                Math.max(
                                  0,
                                  ranking.contribution * 100,
                                ),
                              )}%`,
                            }}
                          />
                        </div>
                        <span className="text-right text-[10px] text-d-muted">
                          corr{' '}
                          {formatUiNumber(ranking.correlation, {
                            maximumFractionDigits: 3,
                          })}{' '}
                          · {formatProbability(ranking.contribution)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </div>
        )}
      </div>

      <MonteCarloCorrelationDialog
        open={correlationDialogOpen}
        allInputs={catalog?.inputs ?? []}
        selectedInputs={selectedInputs}
        correlations={correlations}
        onCorrelationChange={updateCorrelation}
        onResetIdentity={() =>
          setCorrelations(identityMatrix(catalog?.inputs.length ?? 0))
        }
        onClose={() => setCorrelationDialogOpen(false)}
      />

      <FloatingAssistant
        tabKey="monte_carlo"
        pageContext="Persisted Monte Carlo configuration, calibrated canonical outputs, percentile distributions, risk probabilities, and sensitivity ranking"
      />
    </div>
  );
}
