'use client';

import Link from 'next/link';

import type {
  AnalysisKpi,
  ModelDiagnosticsResponse,
} from '@/lib/calculation-api-types';
import type { ActiveAnalysisContextValue } from '@/app/ActiveAnalysisContext';
import {
  formatAnalysisValue,
  formatUiNumber,
} from '@/lib/ui-number-format';

function statusCopy(
  analysis: ActiveAnalysisContextValue,
): { title: string; detail: string; color: string } {
  if (analysis.loadStatus === 'error') {
    return {
      title: 'Unavailable',
      detail: analysis.error?.message ?? 'Unable to load analysis.',
      color: 'text-red-400',
    };
  }
  if (analysis.loadStatus === 'loading') {
    return {
      title: 'Loading',
      detail: 'Reading persisted calculation state.',
      color: 'text-gold-400',
    };
  }
  if (analysis.status === 'ready') {
    return {
      title:
        analysis.activeRunKind === 'override'
          ? 'Override run'
          : 'Baseline run',
      detail: `Run ${analysis.activeRunId?.slice(0, 8)}`,
      color: 'text-emerald-400',
    };
  }
  if (analysis.status === 'needs_calculation') {
    return {
      title: 'Calculation required',
      detail: 'The model is prepared but has no persisted run.',
      color: 'text-amber-400',
    };
  }
  if (analysis.status === 'needs_readiness') {
    return {
      title: 'Preparing',
      detail: 'Waiting for a canonical calculation graph.',
      color: 'text-gold-400',
    };
  }
  return {
    title: 'No model',
    detail: 'Upload and calculate a model to populate this page.',
    color: 'text-d-muted',
  };
}

export default function AnalysisStatusSidebar({
  analysis,
  kpis = [],
  diagnostics = null,
  featuredKpi = false,
  wide = false,
}: {
  analysis: ActiveAnalysisContextValue;
  kpis?: AnalysisKpi[];
  diagnostics?: ModelDiagnosticsResponse | null;
  featuredKpi?: boolean;
  wide?: boolean;
}) {
  const status = statusCopy(analysis);
  return (
    <aside
      className={`flex w-full flex-shrink-0 flex-col gap-4 ${
        wide ? 'lg:w-[21rem]' : 'lg:w-60'
      }`}
    >
      <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
        <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">
          Calculation status
        </div>
        <div className={`text-xl font-bold ${status.color}`}>
          {status.title}
        </div>
        <p className="text-[10px] text-d-muted mt-2 break-words">
          {status.detail}
        </p>
        {analysis.status !== 'ready' && (
          <Link
            href="/"
            className="inline-flex mt-3 text-xs text-gold-400 hover:underline"
          >
            Open calculation setup
          </Link>
        )}
      </section>

      <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
        <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">
          Live model KPIs
        </div>
        <div className="grid grid-cols-2 gap-2">
          {kpis.slice(0, 6).map((kpi) => (
            <div
              key={kpi.slot}
              className={
                featuredKpi
                  ? 'col-span-2 min-w-0 rounded-lg border border-d-border bg-d-bg p-4'
                  : 'min-w-0 rounded bg-d-bg p-2'
              }
            >
              <div
                className={
                  featuredKpi
                    ? 'truncate text-[10px] uppercase tracking-wide text-d-muted'
                    : 'truncate text-[9px] text-d-muted'
                }
              >
                {kpi.label}
              </div>
              <div
                className={`${
                  featuredKpi ? 'mt-2 text-3xl' : 'text-base'
                } truncate font-bold ${
                  kpi.availability_status === 'available'
                    ? featuredKpi
                      ? 'text-gold-400'
                      : 'text-white'
                    : 'text-d-muted'
                }`}
              >
                {formatAnalysisValue(
                  kpi.role,
                  kpi.value,
                  kpi.unit,
                  kpi.display_value,
                )}
              </div>
              <div
                className={`${
                  featuredKpi ? 'mt-2 text-[9px]' : 'text-[8px]'
                } truncate text-d-muted`}
              >
                {featuredKpi
                  ? 'Current deterministic calculation'
                  : (kpi.validation_status ?? kpi.quality_status)}
              </div>
            </div>
          ))}
          {kpis.length === 0 && (
            <p className="col-span-2 text-xs text-d-muted">
              Unavailable
            </p>
          )}
        </div>
      </section>

      <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
        <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">
          Extraction diagnostics
        </div>
        {diagnostics ? (
          <div className="space-y-2 text-xs">
            <div className="flex justify-between gap-2">
              <span className="text-d-muted">Validation</span>
              <span className="text-white">
                {diagnostics.validation_status}
              </span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-d-muted">Sheets</span>
              <span className="text-white">
                {formatUiNumber(diagnostics.detected_sheets.length, {
                  maximumFractionDigits: 0,
                })}
              </span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-d-muted">Errors</span>
              <span
                className={
                  diagnostics.error_count > 0
                    ? 'text-red-400'
                    : 'text-emerald-400'
                }
              >
                {formatUiNumber(diagnostics.error_count, {
                  maximumFractionDigits: 0,
                })}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-d-muted">Unavailable</p>
        )}
      </section>
    </aside>
  );
}
