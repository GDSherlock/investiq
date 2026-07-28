'use client';

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { AnalysisChart } from '@/lib/calculation-api-types';

const SERIES_COLORS = [
  '#60a5fa',
  '#34d399',
  '#f59e0b',
  '#a78bfa',
  '#f87171',
  '#22d3ee',
];

type ChartVariant = 'bar' | 'line' | 'area';

function numericValue(value: string | null): number | null {
  if (value === null) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function buildChartRows(chart: AnalysisChart) {
  const rows = new Map<
    number,
    Record<string, string | number | null>
  >();
  for (const series of chart.series) {
    for (const point of series.points) {
      const row = rows.get(point.period_index) ?? {
        period_index: point.period_index,
        period: point.period ?? String(point.period_index),
      };
      row[series.role] = numericValue(point.value);
      rows.set(point.period_index, row);
    }
  }
  return Array.from(rows.values()).sort(
    (left, right) =>
      Number(left.period_index) - Number(right.period_index),
  );
}

export default function PersistedAnalysisChart({
  chart,
  variant = 'line',
  height = 230,
}: {
  chart: AnalysisChart;
  variant?: ChartVariant;
  height?: number;
}) {
  const rows = buildChartRows(chart);
  const unit = chart.series.find((series) => series.unit)?.unit;

  return (
    <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-5 min-w-0">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-white">
            {chart.title}
          </h2>
          <p className="text-[10px] text-d-muted mt-1">
            {chart.source_type === 'derived'
              ? 'Derived from persisted canonical series'
              : 'Persisted calculation output'}
            {chart.fallback_used
              ? ` · fallback: ${chart.fallback_used}`
              : ''}
          </p>
        </div>
        {unit && (
          <span className="text-[10px] text-d-muted bg-d-bg px-2 py-0.5 rounded shrink-0">
            {unit}
          </span>
        )}
      </div>

      {rows.length === 0 || chart.series.length === 0 ? (
        <div
          className="flex items-center justify-center text-xs text-d-muted"
          style={{ height }}
        >
          Unavailable
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          {variant === 'bar' ? (
            <BarChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
              <XAxis dataKey="period" tick={{ fontSize: 9 }} />
              <YAxis tick={{ fontSize: 9 }} />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  backgroundColor: '#111C44',
                  border: '1px solid #1B2B65',
                  color: '#A3AED0',
                }}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <ReferenceLine y={0} stroke="#94a3b8" />
              {chart.series.map((item, index) => (
                <Bar
                  key={item.role}
                  dataKey={item.role}
                  name={item.label}
                  fill={
                    SERIES_COLORS[index % SERIES_COLORS.length]
                  }
                  radius={[2, 2, 0, 0]}
                />
              ))}
            </BarChart>
          ) : variant === 'area' && chart.series.length === 1 ? (
            <AreaChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
              <XAxis dataKey="period" tick={{ fontSize: 9 }} />
              <YAxis tick={{ fontSize: 9 }} />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  backgroundColor: '#111C44',
                  border: '1px solid #1B2B65',
                  color: '#A3AED0',
                }}
              />
              <ReferenceLine y={0} stroke="#94a3b8" />
              <Area
                type="monotone"
                dataKey={chart.series[0].role}
                name={chart.series[0].label}
                stroke={SERIES_COLORS[0]}
                fill={SERIES_COLORS[0]}
                fillOpacity={0.2}
                connectNulls={false}
              />
            </AreaChart>
          ) : (
            <LineChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
              <XAxis dataKey="period" tick={{ fontSize: 9 }} />
              <YAxis tick={{ fontSize: 9 }} />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  backgroundColor: '#111C44',
                  border: '1px solid #1B2B65',
                  color: '#A3AED0',
                }}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              {chart.series.map((item, index) => (
                <Line
                  key={item.role}
                  type="monotone"
                  dataKey={item.role}
                  name={item.label}
                  stroke={
                    SERIES_COLORS[index % SERIES_COLORS.length]
                  }
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      )}
    </section>
  );
}
