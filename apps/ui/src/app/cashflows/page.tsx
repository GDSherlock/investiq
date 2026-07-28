'use client';

import { useEffect, useRef, useState } from 'react';

import { useActiveAnalysis } from '../ActiveAnalysisContext';
import FloatingAssistant from '../FloatingAssistant';
import AnalysisStatusSidebar from '@/components/analysis/AnalysisStatusSidebar';
import PersistedAnalysisChart from '@/components/analysis/PersistedAnalysisChart';
import {
  getCashFlowAnalysis,
  getModelDiagnostics,
  getOverviewAnalysis,
} from '@/lib/api';
import type {
  AnalysisChart,
  CashFlowAnalysisResponse,
  ModelDiagnosticsResponse,
  OverviewAnalysisResponse,
} from '@/lib/calculation-api-types';

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

export default function CashFlowsPage() {
  const analysis = useActiveAnalysis();
  const requestRevision = useRef(0);
  const [cashFlow, setCashFlow] =
    useState<CashFlowAnalysisResponse | null>(null);
  const [overview, setOverview] =
    useState<OverviewAnalysisResponse | null>(null);
  const [diagnostics, setDiagnostics] =
    useState<ModelDiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const revision = ++requestRevision.current;
    if (
      analysis.status !== 'ready' ||
      analysis.activeRunId === null ||
      analysis.modelVersionId === null
    ) {
      setCashFlow(null);
      setOverview(null);
      setDiagnostics(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([
      getCashFlowAnalysis(analysis.activeRunId),
      getOverviewAnalysis(analysis.activeRunId),
      getModelDiagnostics(analysis.modelVersionId),
    ])
      .then(([nextCashFlow, nextOverview, nextDiagnostics]) => {
        if (
          revision !== requestRevision.current ||
          nextCashFlow.calculation_run_id !== analysis.activeRunId ||
          nextCashFlow.model_version_id !== analysis.modelVersionId
        ) {
          return;
        }
        setCashFlow(nextCashFlow);
        setOverview(nextOverview);
        setDiagnostics(nextDiagnostics);
      })
      .catch((caught) => {
        if (revision === requestRevision.current) {
          setError(
            caught instanceof Error
              ? caught
              : new Error('Unable to load cash flow analysis.'),
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

  const charts = cashFlow?.charts ?? [];
  const projectFcf = chartBySlot(
    charts,
    'annual_project_free_cash_flow',
    'Annual project free cash flow',
  );
  const equityCashFlow = chartBySlot(
    charts,
    'annual_equity_cash_flow',
    'Annual equity cash flow',
  );
  const cfadsDebt = chartBySlot(
    charts,
    'cfads_vs_debt_service',
    'CFADS vs debt service',
  );
  const dscr = chartBySlot(
    charts,
    'dscr_vs_covenant',
    'DSCR vs covenant',
  );
  const cumulative = chartBySlot(
    charts,
    'cumulative_cash_flow',
    'Cumulative cash flow',
  );
  const debt = chartBySlot(
    charts,
    'debt_balance_profile',
    'Debt balance profile',
  );
  const capex = chartBySlot(
    charts,
    'capex_construction_profile',
    'Capex construction profile',
  );
  const interestPrincipal = chartBySlot(
    charts,
    'interest_and_principal_profile',
    'Interest and principal profile',
  );

  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <AnalysisStatusSidebar
        analysis={analysis}
        kpis={overview?.kpis}
        diagnostics={diagnostics}
      />

      <div className="flex-1 min-w-0 space-y-4">
        <section className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg">📊</span>
                <h1 className="text-lg font-semibold text-white">
                  Cash flow and debt service
                </h1>
              </div>
              <p className="text-xs text-d-muted mt-1">
                Deterministic persisted cash flows · coverage · repayment
              </p>
            </div>
            <div className="text-[10px] text-d-muted bg-d-bg px-3 py-2 rounded-lg">
              {cashFlow
                ? `Run ${cashFlow.calculation_run_id.slice(0, 8)}`
                : loading
                  ? 'Loading persisted run…'
                  : 'Unavailable'}
            </div>
          </div>
        </section>

        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-950/30 p-4 text-sm text-red-300">
            {error.message}
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <PersistedAnalysisChart
            chart={projectFcf}
            variant="bar"
            height={260}
          />
          <PersistedAnalysisChart
            chart={equityCashFlow}
            variant="bar"
            height={260}
          />
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <PersistedAnalysisChart chart={cfadsDebt} variant="bar" />
          <PersistedAnalysisChart chart={dscr} variant="line" />
          <PersistedAnalysisChart
            chart={cumulative}
            variant="area"
          />
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <PersistedAnalysisChart chart={debt} variant="area" />
          <PersistedAnalysisChart chart={capex} variant="bar" />
          <PersistedAnalysisChart
            chart={interestPrincipal}
            variant="bar"
          />
        </div>

        <section className="bg-d-card rounded-lg border border-d-border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
            <span className="text-d-muted">
              Null periods remain gaps; no workbook cache or simulated
              fallback is used.
            </span>
            <span className="text-d-muted">
              Cumulative series source: {cumulative.source_type}
            </span>
          </div>
        </section>
      </div>

      <FloatingAssistant
        tabKey="cash_flow"
        pageContext="Persisted deterministic project and equity cash flows, CFADS, debt service, DSCR, cumulative cash, debt, capex, interest, and principal"
      />
    </div>
  );
}
