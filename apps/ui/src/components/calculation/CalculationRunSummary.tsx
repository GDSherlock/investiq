import type { CalculationReadinessResponse } from '../../lib/calculation-api-types';
import {
  formatSupportedPercentage,
  type TechnicalDetail,
} from '../../lib/model-preparation-view';
import { formatUiNumber } from '../../lib/ui-number-format';

import { TechnicalDetails } from './TechnicalDetails';

interface CalculationRunSummaryProps {
  readiness:
    | Pick<CalculationReadinessResponse, 'status' | 'summary'>
    | null;
  phaseLabel: string;
  hasWarnings?: boolean;
  hasError?: boolean;
  details: TechnicalDetail[];
}

function MetricIcon({
  kind,
}: {
  kind: 'formula' | 'supported' | 'nodes' | 'edges';
}) {
  if (kind === 'formula') {
    return (
      <span className="font-serif text-2xl italic" aria-hidden="true">
        ƒx
      </span>
    );
  }
  if (kind === 'supported') {
    return (
      <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="m8 12 2.5 2.5L16 9" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (kind === 'nodes') {
    return (
      <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden="true">
        <circle cx="6" cy="6" r="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="18" cy="6" r="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="12" cy="18" r="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="m7.7 7.2 3.1 8.6M16.3 7.2l-3.1 8.6M8 6h8" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden="true">
      <path d="M5 7h8M11 17h8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="16" cy="7" r="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="8" cy="17" r="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function Metric({
  icon,
  label,
  value,
  note,
}: {
  icon: 'formula' | 'supported' | 'nodes' | 'edges';
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="flex min-w-0 items-center gap-4">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-navy-100 text-slate-300">
        <MetricIcon kind={icon} />
      </div>
      <div className="min-w-0">
        <div className="text-xs text-d-muted">{label}</div>
        <div className="mt-0.5 text-2xl font-medium tabular-nums text-white">
          {value}
        </div>
        <div className="mt-0.5 text-xs text-d-muted">{note}</div>
      </div>
    </div>
  );
}

export function CalculationRunSummary({
  readiness,
  phaseLabel,
  hasWarnings = false,
  hasError = false,
  details,
}: CalculationRunSummaryProps) {
  const summary = readiness?.summary ?? {
    formula_cells_total: 0,
    formula_cells_supported: 0,
    graph_nodes: 0,
    graph_edges: 0,
  };
  const supportedPercentage = formatSupportedPercentage(
    summary.formula_cells_supported,
    summary.formula_cells_total,
  );
  const status = readiness?.status ?? 'waiting';
  const warning = hasWarnings || status === 'ready_with_warning';
  const failed = hasError || status === 'failed';
  const ready = status === 'ready' || status === 'ready_with_warning';

  return (
    <section className="rounded-xl border border-d-border bg-d-card/45 p-5 shadow-[0_18px_50px_rgba(0,0,0,0.14)] sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Run summary</h2>
          <p className="mt-1 text-sm text-d-muted">
            Calculation preparation and graph coverage
          </p>
        </div>
        <TechnicalDetails details={details} />
      </div>

      <div className="mt-6 grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          icon="formula"
          label="Formulas"
          value={formatUiNumber(summary.formula_cells_total, {
            maximumFractionDigits: 0,
          })}
          note="Total"
        />
        <Metric
          icon="supported"
          label="Supported"
          value={formatUiNumber(summary.formula_cells_supported, {
            maximumFractionDigits: 0,
          })}
          note={supportedPercentage}
        />
        <Metric
          icon="nodes"
          label="Graph nodes"
          value={formatUiNumber(summary.graph_nodes, {
            maximumFractionDigits: 0,
          })}
          note="Total"
        />
        <Metric
          icon="edges"
          label="Graph edges"
          value={formatUiNumber(summary.graph_edges, {
            maximumFractionDigits: 0,
          })}
          note="Total"
        />
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-x-10 gap-y-3 border-t border-d-border pt-4 text-sm">
        <div>
          <span className="text-d-muted">Phase</span>
          <span
            className={`ml-3 inline-flex rounded px-2 py-1 text-xs font-medium ${
              failed
                ? 'bg-red-500/10 text-red-300'
                : warning
                  ? 'bg-amber-500/10 text-amber-300'
                  : ready
                  ? 'bg-emerald-500/10 text-emerald-300'
                  : 'bg-slate-500/10 text-slate-300'
            }`}
          >
            {phaseLabel}
          </span>
        </div>
        <div>
          <span className="text-d-muted">Readiness</span>
          <span className="ml-3 font-mono text-xs text-slate-200">
            {status}
          </span>
        </div>
      </div>
    </section>
  );
}
