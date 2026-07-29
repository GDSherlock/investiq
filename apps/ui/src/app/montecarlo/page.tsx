'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
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
import {
  cancelMonteCarloRun,
  createMonteCarloRun,
  getMonteCarloInputs,
  getMonteCarloRun,
  getMonteCarloRunHistory,
} from '@/lib/api';
import type {
  MonteCarloConfiguredInput,
  MonteCarloDistributionType,
  MonteCarloEligibleInput,
  MonteCarloInputCatalogResponse,
  MonteCarloMetricResult,
  MonteCarloOutputRole,
  MonteCarloRunResponse,
} from '@/lib/calculation-api-types';
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

const OUTPUT_LABELS: Record<MonteCarloOutputRole, string> = {
  project_irr: 'Project IRR',
  equity_irr: 'Equity IRR',
  project_npv: 'Project NPV',
  equity_npv: 'Equity NPV',
  minimum_dscr: 'Minimum DSCR',
};

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

function positiveSpread(value: number): number {
  return Math.max(Math.abs(value) * 0.1, 0.1);
}

function defaultParameters(
  input: MonteCarloEligibleInput,
  distributionType: MonteCarloDistributionType = 'normal',
): Record<string, string> {
  const current = numeric(input.current_value);
  const spread = positiveSpread(current);
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
}: {
  metric: MonteCarloMetricResult;
}) {
  if (
    metric.availability_status !== 'available' ||
    metric.percentiles === null
  ) {
    return (
      <section className="rounded-lg border border-d-border bg-d-card p-4">
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
  return (
    <section className="rounded-lg border border-d-border bg-d-card p-4">
      <div className="text-[10px] uppercase tracking-wider text-d-muted">
        {metric.label}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {(['p10', 'p50', 'p90'] as const).map((percentile) => (
          <div key={percentile}>
            <div className="text-[9px] uppercase text-d-muted">
              {percentile}
            </div>
            <div className="text-sm font-semibold text-white">
              {formatMetricValue(
                metric.role,
                metric.percentiles?.[percentile],
              )}
            </div>
          </div>
        ))}
      </div>
      {Object.entries(metric.probabilities).map(([label, value]) => (
        <div
          key={label}
          className="mt-3 flex justify-between gap-3 border-t border-d-border pt-2 text-[10px]"
        >
          <span className="text-d-muted">
            {label.replaceAll('_', ' ')}
          </span>
          <span className="text-emerald-400">
            {formatProbability(value)}
          </span>
        </div>
      ))}
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
    <section className="rounded-lg border border-d-border bg-d-card p-5 min-w-0">
      <h2 className="text-sm font-semibold text-white">
        {metric.label} distribution
      </h2>
      <p className="mt-1 text-[10px] text-d-muted">
        Persisted bounded histogram · no per-trial calculation runs
      </p>
      {rows.length === 0 ? (
        <div className="flex h-56 items-center justify-center text-xs text-d-muted">
          Unavailable
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={230}>
          <BarChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
            <XAxis
              dataKey="bucket"
              interval="preserveStartEnd"
              tick={{ fontSize: 8 }}
            />
            <YAxis
              tick={{ fontSize: 9 }}
              tickFormatter={(value: number) =>
                formatUiNumber(value, {
                  maximumFractionDigits: 0,
                })
              }
            />
            <Tooltip
              contentStyle={{
                fontSize: 11,
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
  const [catalog, setCatalog] =
    useState<MonteCarloInputCatalogResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftInput>>(
    {},
  );
  const [correlations, setCorrelations] = useState<number[][]>([]);
  const [selectedOutputs, setSelectedOutputs] = useState<
    MonteCarloOutputRole[]
  >([]);
  const [trialCount, setTrialCount] = useState(50000);
  const [randomSeed, setRandomSeed] = useState(1729);
  const [run, setRun] = useState<MonteCarloRunResponse | null>(null);
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
        setSelectedOutputs(nextCatalog.supported_output_roles);
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
      if (selectedOutputs.length === 0) {
        throw new Error('Select at least one output metric.');
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
          selected_output_roles: selectedOutputs,
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

  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <AnalysisStatusSidebar analysis={analysis} />

      <div className="flex-1 min-w-0 space-y-4">
        <section className="rounded-lg border border-d-border bg-d-card p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg">🎲</span>
                <h1 className="text-lg font-semibold text-white">
                  Monte Carlo simulation engine
                </h1>
              </div>
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
                disabled={!canConfigure || submitting}
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
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
            <div className="space-y-3">
              {catalog.inputs.length === 0 && (
                <section className="rounded-lg border border-d-border bg-d-card p-5 text-xs text-d-muted">
                  No editable stochastic-eligible canonical parameters
                  are available.
                </section>
              )}
              {catalog.inputs.map((input) => {
                const draft = drafts[input.parameter_id];
                if (!draft) {
                  return null;
                }
                return (
                  <section
                    key={input.parameter_id}
                    className="rounded-lg border border-d-border bg-d-card p-4"
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

            <div className="min-w-0 space-y-4">
              <section className="rounded-lg border border-d-border bg-d-card p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-white">
                      Simulation outputs
                    </h2>
                    <p className="mt-1 text-[10px] text-d-muted">
                      Only reviewed canonical output bindings are
                      selectable.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    {catalog.supported_output_roles.map((role) => (
                      <label
                        key={role}
                        className="flex items-center gap-1.5 text-[10px] text-white"
                      >
                        <input
                          type="checkbox"
                          checked={selectedOutputs.includes(role)}
                          onChange={(event) =>
                            setSelectedOutputs((current) =>
                              event.target.checked
                                ? [...current, role]
                                : current.filter(
                                    (candidate) => candidate !== role,
                                  ),
                            )
                          }
                          className="accent-gold-500"
                        />
                        {OUTPUT_LABELS[role]}
                      </label>
                    ))}
                  </div>
                </div>
              </section>

              {selectedInputs.length > 1 && (
                <section className="overflow-x-auto rounded-lg border border-d-border bg-d-card p-4">
                  <h2 className="text-sm font-semibold text-white">
                    Correlation matrix
                  </h2>
                  <p className="mt-1 text-[10px] text-d-muted">
                    Symmetric positive-definite matrix required.
                  </p>
                  <table className="mt-3 min-w-full text-[9px]">
                    <thead>
                      <tr>
                        <th className="p-1" />
                        {selectedInputs.map((input) => (
                          <th
                            key={input.parameter_id}
                            className="max-w-24 truncate p-1 text-d-muted"
                          >
                            {input.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {selectedInputs.map((rowInput) => {
                        const row = catalog.inputs.findIndex(
                          (input) =>
                            input.parameter_id ===
                            rowInput.parameter_id,
                        );
                        return (
                          <tr key={rowInput.parameter_id}>
                            <th className="max-w-28 truncate p-1 text-left text-d-muted">
                              {rowInput.label}
                            </th>
                            {selectedInputs.map((columnInput) => {
                              const column = catalog.inputs.findIndex(
                                (input) =>
                                  input.parameter_id ===
                                  columnInput.parameter_id,
                              );
                              return (
                                <td
                                  key={columnInput.parameter_id}
                                  className="p-1"
                                >
                                  <input
                                    type="number"
                                    min={-1}
                                    max={1}
                                    step={0.05}
                                    disabled={row === column}
                                    value={
                                      correlations[row]?.[column] ?? 0
                                    }
                                    onChange={(event) =>
                                      updateCorrelation(
                                        row,
                                        column,
                                        event.target.value,
                                      )
                                    }
                                    className="w-16 rounded border border-d-border bg-d-bg p-1 text-center text-white disabled:opacity-50"
                                  />
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </section>
              )}

              <section className="rounded-lg border border-d-border bg-d-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-d-muted">
                      Persisted run status
                    </div>
                    <div className="mt-1 text-base font-semibold text-white">
                      {persistedStatus}
                    </div>
                  </div>
                  {run && (
                    <div className="text-right text-[9px] text-d-muted">
                      <div>
                        Run {run.monte_carlo_run_id.slice(0, 8)}
                      </div>
                      <div>
                        {run.method_version} ·{' '}
                        {formatUiNumber(run.trial_count, {
                          maximumFractionDigits: 0,
                        })}{' '}
                        trials
                      </div>
                      {run.runtime_ms !== null && (
                        <div>
                          {formatUiNumber(run.runtime_ms)} ms
                        </div>
                      )}
                    </div>
                  )}
                </div>
                {run?.error_message && (
                  <p className="mt-3 text-xs text-red-300">
                    {run.error_code}: {run.error_message}
                  </p>
                )}
              </section>

              {metrics.length > 0 && (
                <>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {metrics.map((metric) => (
                      <MetricCard key={metric.role} metric={metric} />
                    ))}
                  </div>
                  <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
                    {metrics.map((metric) => (
                      <DistributionChart
                        key={metric.role}
                        metric={metric}
                      />
                    ))}
                  </div>
                </>
              )}

              <section className="rounded-lg border border-d-border bg-d-card p-5">
                <h2 className="text-sm font-semibold text-white">
                  Sensitivity ranking
                </h2>
                <p className="mt-1 text-[10px] text-d-muted">
                  Correlation and contribution computed from persisted
                  trial outputs.
                </p>
                {rankingMetric === null ? (
                  <div className="flex h-28 items-center justify-center text-xs text-d-muted">
                    Unavailable
                  </div>
                ) : (
                  <div className="mt-4 space-y-3">
                    {rankingMetric.rankings.map((ranking) => (
                      <div key={ranking.parameter_id}>
                        <div className="mb-1 flex justify-between gap-3 text-[10px]">
                          <span className="text-white">
                            {ranking.label}
                          </span>
                          <span className="text-d-muted">
                            corr{' '}
                            {formatUiNumber(ranking.correlation, {
                              maximumFractionDigits: 3,
                            })}{' '}
                            ·{' '}
                            {formatProbability(
                              ranking.contribution,
                            )}
                          </span>
                        </div>
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
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </div>
        )}
      </div>

      <FloatingAssistant
        tabKey="monte_carlo"
        pageContext="Persisted Monte Carlo configuration, calibrated canonical outputs, percentile distributions, risk probabilities, and sensitivity ranking"
      />
    </div>
  );
}
