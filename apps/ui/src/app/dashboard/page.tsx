'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';

import { useActiveAnalysis } from '../ActiveAnalysisContext';
import FloatingAssistant from '../FloatingAssistant';
import AnalysisStatusSidebar from '@/components/analysis/AnalysisStatusSidebar';
import PersistedAnalysisChart from '@/components/analysis/PersistedAnalysisChart';
import {
  getModelDiagnostics,
  getOverviewAnalysis,
} from '@/lib/api';
import type {
  AnalysisChart,
  AnalysisKpi,
  ModelDiagnosticsResponse,
  OverviewAnalysisResponse,
} from '@/lib/calculation-api-types';
import {
  formatAnalysisValue,
  formatUiNumber,
} from '@/lib/ui-number-format';

const CAPITAL_COLORS = ['#3b82f6', '#ef4444', '#34d399'];

function chartBySlot(
  charts: AnalysisChart[],
  slot: string,
  title: string,
): AnalysisChart {
  return (
    charts.find((chart) => chart.slot === slot) ?? {
      slot,
      title,
      availability_status: 'unavailable',
      source_type: 'unavailable',
      fallback_used: null,
      series: [],
    }
  );
}

function CapitalStructure({ chart }: { chart: AnalysisChart }) {
  const data = chart.series
    .map((series) => {
      const point = [...series.points]
        .reverse()
        .find((candidate) => candidate.value !== null);
      return {
        name: series.label,
        value: point?.value === null ? null : Number(point?.value),
      };
    })
    .filter(
      (item): item is { name: string; value: number } =>
        item.value !== null && Number.isFinite(item.value),
    );

  return (
    <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-5 min-w-0">
      <h2 className="text-sm font-semibold text-white">
        Capital structure
      </h2>
      <p className="text-[10px] text-d-muted mt-1">
        {chart.fallback_used
          ? `Persisted amounts · fallback: ${chart.fallback_used}`
          : 'Persisted debt and equity proportions'}
      </p>
      {data.length < 2 ? (
        <div className="h-[230px] flex items-center justify-center text-xs text-d-muted">
          Unavailable
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={190}>
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={78}
                stroke="none"
              >
                {data.map((item, index) => (
                  <Cell
                    key={item.name}
                    fill={
                      CAPITAL_COLORS[index % CAPITAL_COLORS.length]
                    }
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  backgroundColor: '#111C44',
                  border: '1px solid #1B2B65',
                  color: '#A3AED0',
                }}
                formatter={(value: number, name: string) => [
                  formatUiNumber(value),
                  name,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap justify-center gap-3 text-[10px]">
            {data.map((item, index) => (
              <span
                key={item.name}
                className="flex items-center gap-1 text-d-muted"
              >
                <span
                  className="w-2 h-2 rounded-sm"
                  style={{
                    backgroundColor:
                      CAPITAL_COLORS[
                        index % CAPITAL_COLORS.length
                      ],
                  }}
                />
                {item.name}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function KpiCard({ kpi }: { kpi: AnalysisKpi }) {
  const available = kpi.availability_status === 'available';
  const valueText = formatAnalysisValue(
    kpi.role,
    kpi.value,
    kpi.unit,
    kpi.display_value,
    {
      maximumFractionDigits:
        kpi.role === 'project_irr' ? 2 : undefined,
    },
  );

  const benchmarkText = kpi.benchmark
    ? `${kpi.benchmark.role.replaceAll('_', ' ')}: ${formatAnalysisValue(
        kpi.benchmark.role,
        kpi.benchmark.value,
        null,
        kpi.benchmark.display_value,
      )}`
    : kpi.validation_status ?? kpi.quality_status;

  return (
    <section
      className={`bg-d-card rounded-lg shadow-sm border-l-4 p-4 min-w-0 ${
        available ? 'border-emerald-500' : 'border-slate-600'
      }`}
    >
      <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium truncate">
        {kpi.label}
      </div>
      <div
        className={`text-2xl font-bold mt-1 truncate ${
          available ? 'text-white' : 'text-d-muted'
        }`}
      >
        {valueText}
      </div>
      <div
        className={`text-[10px] mt-1 truncate ${
          available ? 'text-emerald-400' : 'text-d-muted'
        }`}
      >
        {kpi.status.replaceAll('_', ' ')}
      </div>
      <div className="text-[10px] text-d-muted truncate">
        {benchmarkText}
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const analysis = useActiveAnalysis();
  const requestRevision = useRef(0);
  const [overview, setOverview] =
    useState<OverviewAnalysisResponse | null>(null);
  const [diagnostics, setDiagnostics] =
    useState<ModelDiagnosticsResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const revision = ++requestRevision.current;
    if (
      analysis.status !== 'ready' ||
      analysis.activeRunId === null ||
      analysis.modelVersionId === null
    ) {
      setOverview(null);
      setDiagnostics(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([
      getOverviewAnalysis(analysis.activeRunId),
      getModelDiagnostics(analysis.modelVersionId),
    ])
      .then(([nextOverview, nextDiagnostics]) => {
        if (
          revision !== requestRevision.current ||
          nextOverview.calculation_run_id !== analysis.activeRunId ||
          nextOverview.model_version_id !== analysis.modelVersionId
        ) {
          return;
        }
        setOverview(nextOverview);
        setDiagnostics(nextDiagnostics);
      })
      .catch((caught) => {
        if (revision === requestRevision.current) {
          setError(
            caught instanceof Error
              ? caught
              : new Error('Unable to load overview.'),
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

  useEffect(
    () => () => {
      requestRevision.current += 1;
    },
    [],
  );

  const charts = overview?.charts ?? [];
  const operating = useMemo(
    () =>
      chartBySlot(
        charts,
        'operating_trajectory',
        'Operating trajectory',
      ),
    [charts],
  );
  const capital = useMemo(
    () =>
      chartBySlot(charts, 'capital_structure', 'Capital structure'),
    [charts],
  );
  const debtCoverage = useMemo(
    () => chartBySlot(charts, 'debt_coverage', 'Debt coverage'),
    [charts],
  );
  const projectCash = useMemo(
    () =>
      chartBySlot(
        charts,
        'project_cash_generation',
        'Project cash generation',
      ),
    [charts],
  );

  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <AnalysisStatusSidebar
        analysis={analysis}
        kpis={overview?.kpis}
        diagnostics={diagnostics}
      />

      <div className="flex-1 min-w-0 space-y-4">
        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-950/30 p-4 text-sm text-red-300">
            {error.message}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-6 gap-3">
          {(overview?.kpis ?? []).map((kpi) => (
            <KpiCard key={kpi.slot} kpi={kpi} />
          ))}
          {!overview &&
            Array.from({ length: 6 }, (_, index) => (
              <section
                key={index}
                className="bg-d-card rounded-lg border-l-4 border-slate-600 p-4"
              >
                <div className="text-[10px] text-d-muted uppercase">
                  Metric {index + 1}
                </div>
                <div className="text-xl font-bold text-d-muted mt-2">
                  {loading ? 'Loading…' : 'Unavailable'}
                </div>
              </section>
            ))}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className="xl:col-span-2">
            <PersistedAnalysisChart
              chart={operating}
              variant="bar"
            />
          </div>
          <CapitalStructure chart={capital} />
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <PersistedAnalysisChart
            chart={debtCoverage}
            variant="line"
          />
          <PersistedAnalysisChart
            chart={projectCash}
            variant="bar"
          />
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <section className="bg-d-card rounded-lg border border-d-border p-5">
            <h2 className="text-sm font-semibold text-white">
              Model health check
            </h2>
            <p className="text-[10px] text-d-muted mt-1 mb-3">
              Persisted extraction coverage and validation
            </p>
            {diagnostics ? (
              <div className="grid grid-cols-2 gap-2 text-xs">
                {[
                  ['Model status', diagnostics.status],
                  ['Validation', diagnostics.validation_status],
                  [
                    'Errors',
                    formatUiNumber(diagnostics.error_count, {
                      maximumFractionDigits: 0,
                    }),
                  ],
                  [
                    'Time-series fields',
                    formatUiNumber(
                      Object.keys(diagnostics.time_series_summary)
                        .length,
                      { maximumFractionDigits: 0 },
                    ),
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="bg-d-bg rounded p-3">
                    <div className="text-d-muted">{label}</div>
                    <div className="text-white font-semibold mt-1">
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-d-muted">Unavailable</p>
            )}
          </section>

          <section className="bg-d-card rounded-lg border border-d-border p-5">
            <h2 className="text-sm font-semibold text-white">
              Detected model sheets
            </h2>
            <p className="text-[10px] text-d-muted mt-1 mb-3">
              Extraction diagnostics, not financial outputs
            </p>
            <div className="flex flex-wrap gap-2">
              {diagnostics?.detected_sheets.map((sheet) => (
                <span
                  key={sheet}
                  className="text-[10px] bg-d-bg text-d-muted px-2 py-1 rounded"
                >
                  {sheet}
                </span>
              ))}
              {diagnostics?.detected_sheets.length === 0 && (
                <span className="text-xs text-d-muted">Unavailable</span>
              )}
            </div>
          </section>
        </div>
      </div>

      <FloatingAssistant
        tabKey="overview"
        pageContext="Persisted canonical overview KPIs, trajectories, capital structure, debt coverage, cash generation, and extraction diagnostics"
      />
    </div>
  );
}
