'use client';

import { buildSensitivityTornadoGeometry } from '../../lib/sensitivity-tornado-geometry';

import type { SensitivityTornadoRow } from '@/lib/sensitivity-analysis';

interface SensitivityTornadoChartProps {
  rows: SensitivityTornadoRow[];
  outputLabel: string;
  formatValue: (value: number | null) => string;
  formatDelta: (value: number) => string;
}

const CHART_WIDTH = 760;
const LABEL_WIDTH = 190;
const PLOT_RIGHT = 28;
const ROW_HEIGHT = 54;
const BAR_HEIGHT = 14;
const TOP_PADDING = 28;
const BOTTOM_PADDING = 42;

function diamondPoints(x: number, y: number, radius = 5): string {
  return `${x},${y - radius} ${x + radius},${y} ${x},${y + radius} ${x - radius},${y}`;
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

  const plotWidth = CHART_WIDTH - LABEL_WIDTH - PLOT_RIGHT;
  const geometry = buildSensitivityTornadoGeometry({
    width: plotWidth,
    rowHeight: ROW_HEIGHT,
    barHeight: BAR_HEIGHT,
    rows: chartRows.map((row) => ({
      targetKey: row.targetKey,
      lowDelta: row.lowDelta,
      highDelta: row.highDelta,
    })),
  });
  const chartHeight = Math.max(320, chartRows.length * ROW_HEIGHT + TOP_PADDING + BOTTOM_PADDING);
  const zeroX = LABEL_WIDTH + geometry.zeroX;

  return (
    <div>
      {chartRows.length > 0 ? (
        <div className="overflow-x-auto">
          <div
            className="min-w-[42rem] sm:min-w-0"
            style={{ height: `${chartHeight}px` }}
            role="img"
            aria-label={`${outputLabel} sensitivity deltas by canonical driver`}
          >
            <svg
              viewBox={`0 0 ${CHART_WIDTH} ${chartHeight}`}
              width="100%"
              height="100%"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <line
                x1={zeroX}
                x2={zeroX}
                y1={TOP_PADDING - 8}
                y2={chartHeight - BOTTOM_PADDING + 4}
                stroke="#cbd5e1"
                strokeOpacity="0.5"
              />
              {geometry.rows.map((geometryRow, index) => {
                const row = chartRows[index];
                const yOffset = TOP_PADDING;
                const low = geometryRow.low;
                const high = geometryRow.high;
                const labelY = yOffset + low.yCenter + 4;
                const lowBarX = low.barX === null ? null : LABEL_WIDTH + low.barX;
                const highBarX = high.barX === null ? null : LABEL_WIDTH + high.barX;
                const lowMarkerX = low.markerX === null ? null : LABEL_WIDTH + low.markerX;
                const highMarkerX = high.markerX === null ? null : LABEL_WIDTH + high.markerX;

                return (
                  <g key={geometryRow.targetKey}>
                    <line
                      x1={LABEL_WIDTH}
                      x2={CHART_WIDTH - PLOT_RIGHT}
                      y1={yOffset + low.yCenter}
                      y2={yOffset + low.yCenter}
                      stroke="rgba(148,163,184,0.12)"
                    />
                    <text
                      x={LABEL_WIDTH - 12}
                      y={labelY}
                      textAnchor="end"
                      fill="#cbd5e1"
                      fontSize="12"
                    >
                      {row.label}
                    </text>
                    {lowBarX !== null ? (
                      <g>
                        <title>{`${row.label}, Low case: ${formatDelta(row.lowDelta as number)}`}</title>
                        <rect
                          x={lowBarX}
                          y={yOffset + low.barY}
                          width={low.barWidth}
                          height={low.barHeight}
                          rx="3"
                          fill="#f87171"
                          fillOpacity="0.58"
                          stroke="#fecaca"
                          strokeWidth="1"
                        />
                        {lowMarkerX !== null ? (
                          <circle
                            cx={lowMarkerX}
                            cy={yOffset + low.yCenter}
                            r="4"
                            fill="#f87171"
                            stroke="#fee2e2"
                            strokeWidth="1"
                          />
                        ) : null}
                      </g>
                    ) : null}
                    {highBarX !== null ? (
                      <g>
                        <title>{`${row.label}, High case: ${formatDelta(row.highDelta as number)}`}</title>
                        <rect
                          x={highBarX}
                          y={yOffset + high.barY}
                          width={high.barWidth}
                          height={high.barHeight}
                          rx="3"
                          fill="#4ade80"
                          fillOpacity="0.58"
                          stroke="#bbf7d0"
                          strokeWidth="1"
                        />
                        {highMarkerX !== null ? (
                          <polygon
                            points={diamondPoints(
                              highMarkerX,
                              yOffset + high.yCenter,
                            )}
                            fill="#4ade80"
                            stroke="#dcfce7"
                            strokeWidth="1"
                          />
                        ) : null}
                      </g>
                    ) : null}
                    {!low.available || !high.available ? (
                      <text
                        x={CHART_WIDTH - PLOT_RIGHT}
                        y={labelY}
                        textAnchor="end"
                        fill="#fcd34d"
                        fontSize="10"
                      >
                        {!low.available && !high.available
                          ? 'Low and High unavailable'
                          : !low.available
                            ? 'Low unavailable'
                            : 'High unavailable'}
                      </text>
                    ) : null}
                  </g>
                );
              })}
              <text x={LABEL_WIDTH} y={chartHeight - 14} fill="#94a3b8" fontSize="11">
                {formatDelta(-geometry.extent)}
              </text>
              <text x={zeroX} y={chartHeight - 14} textAnchor="middle" fill="#94a3b8" fontSize="11">
                {formatDelta(0)}
              </text>
              <text x={CHART_WIDTH - PLOT_RIGHT} y={chartHeight - 14} textAnchor="end" fill="#94a3b8" fontSize="11">
                {formatDelta(geometry.extent)}
              </text>
              <text x={LABEL_WIDTH} y="16" fill="#f87171" fontSize="11">
                ● Low case
              </text>
              <text x={LABEL_WIDTH + 88} y="16" fill="#4ade80" fontSize="11">
                ◆ High case
              </text>
            </svg>
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
