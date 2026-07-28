'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';

import { useActiveAnalysis } from '../ActiveAnalysisContext';
import FloatingAssistant from '../FloatingAssistant';
import { usePersona } from '../PersonaContext';
import AnalysisStatusSidebar from '@/components/analysis/AnalysisStatusSidebar';
import {
  createCanonicalReport,
  getCanonicalReport,
  getCanonicalReportHistory,
} from '@/lib/api';
import type { CanonicalReportResponse } from '@/lib/calculation-api-types';

const REPORT_STATUSES = [
  'queued',
  'running',
  'completed',
  'failed',
] as const;

const FIXED_SECTION_LABELS = [
  'Executive recommendation',
  'Project and transaction overview',
  'Key investment assumptions',
  'Construction and completion risk',
  'Operating and revenue profile',
  'Financial returns',
  'Funding and capital structure',
  'Debt service and covenant analysis',
  'Sensitivity analysis',
  'Monte Carlo results',
  'Key risks and mitigants',
  'Approval conditions',
  'Final recommendation',
];

function availabilityStyle(status: string): string {
  if (status === 'available') {
    return 'border-emerald-500/40 bg-emerald-950/20 text-emerald-400';
  }
  if (status === 'partial') {
    return 'border-amber-500/40 bg-amber-950/20 text-amber-400';
  }
  return 'border-d-border bg-d-bg text-d-muted';
}

export default function ReportsPage() {
  const analysis = useActiveAnalysis();
  const { persona } = usePersona();
  const requestRevision = useRef(0);
  const [history, setHistory] = useState<CanonicalReportResponse[]>([]);
  const [report, setReport] = useState<CanonicalReportResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const revision = ++requestRevision.current;
    if (
      analysis.status !== 'ready' ||
      analysis.modelVersionId === null ||
      analysis.activeRunId === null
    ) {
      setHistory([]);
      setReport(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    getCanonicalReportHistory(analysis.modelVersionId)
      .then((response) => {
        if (
          revision !== requestRevision.current ||
          response.model_version_id !== analysis.modelVersionId
        ) {
          return;
        }
        setHistory(response.reports);
        setReport(
          response.reports.find(
            (candidate) =>
              candidate.calculation_run_id === analysis.activeRunId &&
              candidate.persona.id === persona.id,
          ) ?? null,
        );
      })
      .catch((caught) => {
        if (revision === requestRevision.current) {
          setError(
            caught instanceof Error
              ? caught
              : new Error('Unable to load report history.'),
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
    persona.id,
  ]);

  useEffect(() => {
    if (
      report === null ||
      !['queued', 'running'].includes(report.status)
    ) {
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      getCanonicalReport(report.report_id)
        .then((next) => {
          if (!active) {
            return;
          }
          setReport(next);
          setHistory((current) => [
            next,
            ...current.filter(
              (candidate) => candidate.report_id !== next.report_id,
            ),
          ]);
        })
        .catch((caught) => {
          if (active) {
            setError(
              caught instanceof Error
                ? caught
                : new Error('Unable to refresh the report.'),
            );
          }
        });
    }, 1000);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [report]);

  useEffect(
    () => () => {
      requestRevision.current += 1;
    },
    [],
  );

  const generate = async () => {
    if (
      analysis.modelVersionId === null ||
      analysis.graphVersionId === null ||
      analysis.activeRunId === null
    ) {
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const next = await createCanonicalReport(
        analysis.modelVersionId,
        {
          graph_version_id: analysis.graphVersionId,
          calculation_run_id: analysis.activeRunId,
          sensitivity_analysis_id: null,
          monte_carlo_run_id: null,
          template_version: 'canonical-ic-paper-v1',
          persona: {
            id: persona.id,
            name: persona.name,
            tone: persona.report_system_addendum.tone,
            emphasis: persona.report_system_addendum.emphasis,
          },
          idempotency_key: crypto.randomUUID(),
        },
      );
      setReport(next);
      setHistory((current) => [
        next,
        ...current.filter(
          (candidate) => candidate.report_id !== next.report_id,
        ),
      ]);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught
          : new Error('Unable to queue the report.'),
      );
    } finally {
      setGenerating(false);
    }
  };

  const reportStatus =
    report !== null && REPORT_STATUSES.includes(report.status)
      ? report.status
      : 'Unavailable';
  const canGenerate =
    analysis.status === 'ready' &&
    analysis.modelVersionId !== null &&
    analysis.graphVersionId !== null &&
    analysis.activeRunId !== null;

  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <AnalysisStatusSidebar analysis={analysis} />

      <div className="flex-1 min-w-0 space-y-4">
        <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg">📄</span>
                <h1 className="text-lg font-semibold text-white">
                  Canonical Report Generator
                </h1>
              </div>
              <p className="text-xs text-d-muted mt-1">
                Frozen calculation evidence · persisted analysis
                artifacts · deterministic template
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="text-left sm:text-right">
                <div className="text-[10px] text-d-muted uppercase tracking-wider">
                  Generating for
                </div>
                <div className="text-sm font-semibold text-white">
                  {persona.name}
                </div>
                <div className="text-[10px] text-d-muted">
                  Investment Committee Paper
                </div>
              </div>
              <button
                type="button"
                onClick={() => void generate()}
                disabled={!canGenerate || generating}
                className="bg-gold-500 hover:bg-gold-600 text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {generating
                  ? 'Queueing…'
                  : 'Generate Investment Committee Paper'}
              </button>
            </div>
          </div>
        </section>

        <section className="bg-gradient-to-r from-d-bg to-d-card rounded-lg border border-d-border p-4">
          <div className="grid grid-cols-1 gap-4 text-xs md:grid-cols-3">
            <div>
              <div className="text-[10px] text-d-muted uppercase tracking-wider font-semibold mb-1">
                Tone
              </div>
              <div className="text-white">
                {persona.report_system_addendum.tone}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-d-muted uppercase tracking-wider font-semibold mb-1">
                Emphasis
              </div>
              <div className="text-white">
                {persona.report_system_addendum.emphasis.join(' · ')}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-d-muted uppercase tracking-wider font-semibold mb-1">
                Governance
              </div>
              <div className="text-amber-400">
                Pending IC review
              </div>
            </div>
          </div>
        </section>

        {analysis.status !== 'ready' && (
          <section className="rounded-lg border border-d-border bg-d-card p-12 text-center">
            <p className="text-sm text-d-muted">
              A persisted calculation run is required before a report
              can be generated.
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

        {canGenerate && (
          <section className="rounded-lg border border-d-border bg-d-card px-4 py-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-d-muted">
                  Report history
                </div>
                <p className="mt-1 text-[10px] text-d-muted">
                  Reloads immutable artifacts; no report is generated on
                  page load.
                </p>
              </div>
              <select
                value={report?.report_id ?? ''}
                onChange={(event) => {
                  const selected = history.find(
                    (candidate) =>
                      candidate.report_id === event.target.value,
                  );
                  setReport(selected ?? null);
                }}
                disabled={loading || history.length === 0}
                className="min-w-64 rounded border border-d-border bg-d-bg px-3 py-2 text-xs text-white disabled:opacity-50"
              >
                <option value="">
                  {loading
                    ? 'Loading history…'
                    : 'No persisted report selected'}
                </option>
                {history.map((item) => (
                  <option key={item.report_id} value={item.report_id}>
                    {item.persona.name} · {item.status} ·{' '}
                    {item.report_id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </div>
          </section>
        )}

        {report &&
          ['queued', 'running'].includes(report.status) && (
            <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-12 text-center">
              <div className="inline-block animate-spin rounded-full h-8 w-8 border-4 border-d-border border-t-gold-500 mb-3" />
              <p className="text-sm text-white">
                Canonical report {report.status}
              </p>
              <p className="text-xs text-d-muted mt-1">
                Evidence {report.evidence_hash.slice(0, 12)} is frozen;
                refreshing is GET-only.
              </p>
            </section>
          )}

        {report?.status === 'failed' && (
          <section className="rounded-lg border border-red-500/50 bg-red-950/30 p-5">
            <h2 className="text-sm font-semibold text-red-300">
              Report generation failed
            </h2>
            <p className="mt-2 text-xs text-red-300">
              {report.error_code}: {report.error_message}
            </p>
          </section>
        )}

        {report?.status === 'completed' && report.artifact && (
          <article className="bg-d-card rounded-lg shadow-sm border border-d-border overflow-hidden">
            <header className="flex flex-col gap-3 border-b border-d-border bg-d-bg px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <span className="text-green-400 text-sm">✓</span>
                <h2 className="text-sm font-semibold text-white">
                  {report.artifact.title}
                </h2>
                <span className="text-[10px] bg-green-900/30 text-green-400 px-2 py-0.5 rounded font-medium">
                  {reportStatus}
                </span>
              </div>
              <div className="text-[10px] text-d-muted">
                Persona: {report.persona.name} · ID:{' '}
                {report.report_id.slice(0, 8)}
              </div>
            </header>

            <div className="p-5 sm:p-7">
              <div className="border-b border-d-border pb-5">
                <h1 className="text-xl font-bold text-white">
                  Investment Committee Paper
                </h1>
                <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
                  <span className="rounded bg-d-bg px-2 py-1 text-d-muted">
                    Calculation {report.calculation_run_id.slice(0, 8)}
                  </span>
                  <span className="rounded bg-d-bg px-2 py-1 text-d-muted">
                    Sensitivity{' '}
                    {report.sensitivity_analysis_id?.slice(0, 8) ??
                      'Unavailable'}
                  </span>
                  <span className="rounded bg-d-bg px-2 py-1 text-d-muted">
                    Monte Carlo{' '}
                    {report.monte_carlo_run_id?.slice(0, 8) ??
                      'Unavailable'}
                  </span>
                  <span className="rounded bg-amber-950/30 px-2 py-1 text-amber-400">
                    {report.artifact.final_recommendation}
                  </span>
                </div>
              </div>

              <div className="divide-y divide-d-border">
                {report.artifact.sections.map((section) => (
                  <section
                    key={section.key}
                    className="py-5"
                    data-source-count={section.source_ids.length}
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <h2 className="text-base font-semibold text-white">
                        {section.ordinal}. {section.title}
                      </h2>
                      <span
                        className={`w-fit rounded border px-2 py-0.5 text-[9px] uppercase ${availabilityStyle(
                          section.availability_status,
                        )}`}
                      >
                        {section.availability_status}
                      </span>
                    </div>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-200">
                      {section.body}
                    </p>
                    {section.source_ids.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {section.source_ids.map((sourceId) => (
                          <span
                            key={sourceId}
                            title={sourceId}
                            className="rounded-full border border-d-border bg-d-bg px-2 py-0.5 text-[9px] text-gold-400"
                          >
                            Evidence {sourceId.slice(0, 8)}
                          </span>
                        ))}
                      </div>
                    )}
                  </section>
                ))}
              </div>

              <footer className="mt-4 border-t border-d-border pt-4 text-[9px] text-d-muted">
                Evidence hash: {report.evidence_hash} · Template:{' '}
                {report.template_version}
              </footer>
            </div>
          </article>
        )}

        {canGenerate && report === null && !loading && (
          <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-12 text-center text-d-muted">
            <p className="text-sm">
              Generate a frozen thirteen-section IC paper for the active
              persisted calculation.
            </p>
            <p className="mt-2 text-[10px]">
              {FIXED_SECTION_LABELS[0]} →{' '}
              {FIXED_SECTION_LABELS[11]} →{' '}
              {FIXED_SECTION_LABELS[12]}
            </p>
          </section>
        )}
      </div>

      <FloatingAssistant
        tabKey="reports"
        pageContext="Canonical persisted Investment Committee Paper with frozen calculation, sensitivity, Monte Carlo, persona, template, and source UUID evidence"
      />
    </div>
  );
}
