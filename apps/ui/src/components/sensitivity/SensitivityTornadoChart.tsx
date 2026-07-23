'use client';

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { SensitivityTornadoRow } from '@/lib/sensitivity-analysis';

interface SensitivityTornadoChartProps {
  rows: SensitivityTornadoRow[];
  outputLabel: string;
  formatValue: (value: number | null) => string;
  formatDelta: (value: number) => string;
}

export function SensitivityTornadoChart({
  rows,
  outputLabel,
  formatValue,
  formatDelta,
}: SensitivityTornadoChartProps) {
  const chartRows = rows.filter(
    (row) => row.lowDelta !== null || row.highDelta !== null,
  );
  const unavailableRows = rows.filter(
    (row) => row.unavailableReason !== null,
  );

  if (rows.length === 0) {
    return (
      <p className="rounded border border-d-border bg-d-bg p-4 text-sm text-d-muted">
        Run an analysis to calculate one-way endpoint cases.
      </p>
    );
  }

  return (
    <div>
      {chartRows.length > 0 ? (
        <div className="overflow-x-auto">
          <div
            className="min-w-[42rem] sm:min-w-0"
            style={{
              height: `${Math.max(320, chartRows.length * 54 + 96)}px`,
            }}
            role="img"
            aria-label={`${outputLabel} sensitivity deltas by canonical driver`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartRows}
                layout="vertical"
                margin={{ top: 12, right: 28, bottom: 18, left: 24 }}
              >
                <CartesianGrid
                  stroke="rgba(148,163,184,0.12)"
                  horizontal={false}
                />
                <XAxis
                  type="number"
                  stroke="#94a3b8"
                  tick={{ fontSize: 11 }}
                  tickFormatter={formatDelta}
                />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={180}
                  stroke="#94a3b8"
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    formatDelta(value),
                    name,
                  ]}
                  contentStyle={{
                    background: '#111827',
                    border: '1px solid #334155',
                    borderRadius: 6,
                  }}
                  labelStyle={{ color: '#e2e8f0' }}
                />
                <Legend />
                <ReferenceLine x={0} stroke="#cbd5e1" strokeOpacity={0.5} />
                <Bar
                  dataKey="lowDelta"
                  name="Low case Δ"
                  fill="#f87171"
                  radius={[3, 3, 3, 3]}
                />
                <Bar
                  dataKey="highDelta"
                  name="High case Δ"
                  fill="#4ade80"
                  radius={[3, 3, 3, 3]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <p className="rounded border border-amber-800/50 bg-amber-900/10 p-4 text-sm text-amber-200">
          Every returned endpoint is unavailable for the selected output.
        </p>
      )}

      <ul className="sr-only">
        {rows.map((row) => (
          <li key={row.targetKey}>
            {row.label}: low {formatValue(row.lowValue)}, current{' '}
            {formatValue(row.currentValue)}, high {formatValue(row.highValue)}.
            Low run {row.lowRunId}; high run {row.highRunId}.
          </li>
        ))}
      </ul>

      {unavailableRows.length > 0 ? (
        <div
          className="mt-4 rounded border border-amber-800/50 bg-amber-900/10 p-3"
          aria-live="polite"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-200">
            Unavailable endpoints
          </p>
          <ul className="mt-2 space-y-1 text-xs text-amber-100">
            {unavailableRows.map((row) => (
              <li key={row.targetKey}>
                {row.label}: {row.unavailableReason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="mt-4 rounded border border-d-border bg-d-bg/70 p-3 text-xs text-d-muted">
        <summary className="cursor-pointer font-medium text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400">
          Case provenance
        </summary>
        <ul className="mt-3 space-y-2">
          {rows.map((row) => (
            <li key={row.targetKey}>
              <span className="font-medium text-slate-200">{row.label}</span>:
              {' '}low input {row.lowInputValue}, run {row.lowRunId}; high input{' '}
              {row.highInputValue}, run {row.highRunId}
              {row.warnings.length > 0
                ? `; ${row.warnings.join('; ')}`
                : ''}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
