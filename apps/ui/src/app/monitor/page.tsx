'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import Link from 'next/link';
import { getModel, createScenario, getMonitor } from '@/lib/api';
import { useScenario } from '../ScenarioContext';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  AreaChart, Area, ReferenceLine,
} from 'recharts';
import FloatingAssistant from '../FloatingAssistant';
import { formatUiNumber } from '@/lib/ui-number-format';

function fmtPct(v: any): string {
  if (v == null) return '—';
  const n = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(n)) return String(v);
  return n < 1
    ? `${formatUiNumber(n * 100, {
        maximumFractionDigits: 1,
      })}%`
    : `${formatUiNumber(n, {
        maximumFractionDigits: 2,
      })}%`;
}

const STATUS_STYLES: Record<string, { dot: string; text: string }> = {
  Done: { dot: 'bg-green-500', text: 'text-green-400' },
  'On track': { dot: 'bg-gold-400', text: 'text-gold-400' },
  Watch: { dot: 'bg-orange-500', text: 'text-orange-400' },
  'At risk': { dot: 'bg-red-500', text: 'text-red-400' },
  Planned: { dot: 'bg-slate-400', text: 'text-d-muted' },
};

export default function MonitorPage() {
  const [modelId, setModelId] = useState('');
  const [model, setModel] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [monLoading, setMonLoading] = useState(false);
  const [monData, setMonData] = useState<any>(null);
  const { scenario } = useScenario();

  /* ── Load model ── */
  const fetchModel = useCallback(async (id: string) => {
    try { setModel(await getModel(id)); } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    const id = localStorage.getItem('investiq_model_id');
    if (id) { setModelId(id); fetchModel(id); } else setLoading(false);
  }, [fetchModel]);

  useEffect(() => {
    const handleVis = () => {
      if (document.visibilityState === 'visible') {
        const id = localStorage.getItem('investiq_model_id');
        if (id && id !== modelId) { setModelId(id); setLoading(true); setMonData(null); fetchModel(id); }
      }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'investiq_model_id' && e.newValue && e.newValue !== modelId) {
        setModelId(e.newValue); setLoading(true); setMonData(null); fetchModel(e.newValue);
      }
    };
    document.addEventListener('visibilitychange', handleVis);
    window.addEventListener('storage', handleStorage);
    return () => { document.removeEventListener('visibilitychange', handleVis); window.removeEventListener('storage', handleStorage); };
  }, [modelId, fetchModel]);

  /* ── Load monitor data ── */
  const loadMonitor = useCallback(async () => {
    if (!modelId) return;
    setMonLoading(true);
    try {
      const scenarioObj = await createScenario(modelId, 'Monitor', { scenario });
      const data = await getMonitor(scenarioObj.id);
      setMonData(data);
    } catch (e) { console.error(e); }
    setMonLoading(false);
  }, [modelId, scenario]);

  useEffect(() => {
    if (model && !monLoading) loadMonitor();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, scenario]);

  /* ── Sidebar data ── */
  const parsed = model?.parsed_json || {};
  const cover = parsed.cover || {};
  const returns = parsed.returns || {};
  const metrics = returns.metrics || [];
  const assumptions = parsed.assumptions || [];

  const kpi = useMemo(() => {
    const m: Record<string, any> = {};
    for (const item of metrics) m[item.metric] = item;
    return {
      irr: m['Project IRR (unlevered)']?.[scenario],
      npv: m['NPV @ WACC (USD M)']?.[scenario],
      payback: m['Payback period (years)']?.[scenario],
      dscr: m['DSCR — average']?.[scenario],
      dscrMin: m['DSCR — minimum (year 2030)']?.[scenario],
    };
  }, [metrics, scenario]);

  const sidebarAssumptions = useMemo(() => {
    return assumptions.map((a: any) => {
      const v = a.value;
      const n = typeof v === 'number' ? v : parseFloat(v);
      let formatted: string;
      if (isNaN(n)) {
        formatted = String(v);
      } else if (a.unit === '%' || (n > 0 && n < 1)) {
        formatted = `${formatUiNumber(n * 100, {
          maximumFractionDigits: 1,
        })}%`;
      } else if (a.unit === '$/MMBtu' || a.unit === '$') {
        formatted = `$${formatUiNumber(n)}`;
      } else {
        formatted = formatUiNumber(n);
      }
      return { label: a.name, value: formatted };
    }).slice(0, 12);
  }, [assumptions]);

  /* ── Chart data ── */
  const capexChartData = useMemo(() => {
    if (!monData?.capex_chart) return [];
    const { quarters, plan, actuals } = monData.capex_chart;
    return quarters.map((q: string, i: number) => ({
      quarter: q,
      Plan: plan[i],
      Actuals: actuals[i],
    }));
  }, [monData]);

  const irrChartData = useMemo(() => {
    if (!monData?.irr_chart) return [];
    return monData.irr_chart.map((d: any) => ({
      quarter: d.quarter,
      'IRR forecast': d.irr,
      'Hurdle 10%': monData.kpis?.hurdle_rate ?? 10,
      'Base 12.3%': monData.kpis?.irr_base ?? 12.3,
    }));
  }, [monData]);

  if (loading) return <div className="flex items-center justify-center h-64 text-d-muted">Loading model...</div>;
  if (!model) return (
    <div className="text-center py-12">
      <p className="text-slate-300 mb-2">No model loaded. Upload a model first.</p>
      <Link href="/" className="text-gold-400 hover:underline">Go to Upload</Link>
    </div>
  );

  const k = monData?.kpis;

  return (
    <div className="flex gap-4">
      {/* ── Left Sidebar ── */}
      <div className="w-56 flex-shrink-0 space-y-4">
        {/* Decision Confidence */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
          <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">Decision Confidence</div>
          <div className="flex items-center gap-2">
            <div className="text-3xl font-bold text-white">{fmtPct(kpi.irr)}</div>
            <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
          </div>
          <div className="text-xs text-green-400 mt-1">▲ Above hurdle — Investable</div>
          <div className="mt-3 space-y-1">
            <div className="flex items-center gap-2 text-xs">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-slate-300">IRR above hurdle</span>
              <span className="ml-auto font-semibold">{fmtPct(kpi.irr)}</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-slate-300">DSCR covenant met</span>
              <span className="ml-auto font-semibold">{kpi.dscr}x</span>
            </div>
          </div>
        </div>

        {/* Live Model KPIs */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
          <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">Live Model KPIs</div>
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">IRR</div>
              <div className="text-lg font-bold text-gold-400">{fmtPct(kpi.irr)}</div>
              <div className="text-[9px] text-d-muted">Base: {fmtPct(kpi.irr)}</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">NPV</div>
              <div className="text-lg font-bold text-gold-400">${kpi.npv}M</div>
              <div className="text-[9px] text-d-muted">@ {fmtPct(assumptions.find((a: any) => a.name === 'WACC (unlevered)')?.value)} WACC</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">PAYBACK</div>
              <div className="text-lg font-bold text-white">{kpi.payback}yr</div>
              <div className="text-[9px] text-d-muted">&lt;12yr target</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">DSCR</div>
              <div className="text-lg font-bold text-white">{kpi.dscr}x</div>
              <div className="text-[9px] text-d-muted">Min: {kpi.dscrMin}x</div>
            </div>
          </div>
        </div>

        {/* Assumptions */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
          <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">Assumptions</div>
          <div className="space-y-1.5">
            {sidebarAssumptions.map((a: { label: string; value: string }) => (
              <div key={a.label} className="flex justify-between text-xs">
                <span className="text-d-muted">{a.label}</span>
                <span className="font-mono font-semibold text-white">{a.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Main Content ── */}
      <div className="flex-1 space-y-4">
        {/* Header */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
                <h1 className="text-lg font-semibold text-white">Performance monitor</h1>
              </div>
              <p className="text-xs text-d-muted mt-1">
                Actuals vs plan · IRR reforecast · Milestone RAG tracker — Q1 2026
              </p>
            </div>
            <div className="flex items-center gap-2">
              {monData?.alert_badge && (
                <span className="bg-orange-900/30 text-orange-400 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
                  ⚠ {monData.alert_badge}
                </span>
              )}
              <button
                onClick={loadMonitor}
                disabled={monLoading}
                className="bg-gold-500 hover:bg-gold-600 text-white text-sm font-semibold
                  px-4 py-2 rounded-lg transition disabled:bg-d-dim flex items-center gap-1.5"
              >
                {monLoading ? <span className="animate-pulse">Loading...</span> : <>↻ Refresh</>}
              </button>
            </div>
          </div>
        </div>

        {monData ? (
          <>
            {/* ── 4 KPI Cards ── */}
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
                <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium">Capex Spent</div>
                <div className="text-2xl font-bold text-white mt-1">${formatUiNumber(k.capex_spent)}M</div>
                <div className="text-xs text-d-muted mt-0.5">{formatUiNumber(k.pct_spent)}% of ${formatUiNumber(k.capex_total)}M</div>
                <div className="text-xs text-orange-400 mt-1">▲ {formatUiNumber(k.overrun_pct)}% above plan</div>
                <div className="text-[10px] text-d-muted mt-0.5">{k.overrun_driver}</div>
              </div>
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
                <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium">Cost Overrun</div>
                <div className={`text-2xl font-bold mt-1 ${k.cost_overrun > 0 ? 'text-orange-400' : 'text-green-400'}`}>
                  {k.cost_overrun > 0 ? '+' : ''}${formatUiNumber(k.cost_overrun)}M
                </div>
              </div>
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
                <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium">Schedule</div>
                <div className={`text-2xl font-bold mt-1 ${k.schedule_status === 'On track' ? 'text-green-400' : 'text-orange-400'}`}>
                  {k.schedule_status}
                </div>
                <div className="text-xs text-d-muted mt-0.5">
                  {formatUiNumber(k.milestones_done, { maximumFractionDigits: 0 })} / {formatUiNumber(k.milestones_total, { maximumFractionDigits: 0 })} milestones
                </div>
                <div className="text-[10px] text-d-muted mt-0.5">Target: {k.target_completion}</div>
              </div>
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
                <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium">IRR Reforecast</div>
                <div className="text-2xl font-bold text-gold-400 mt-1">{formatUiNumber(k.irr_reforecast)}%</div>
                <div className={`text-xs mt-0.5 ${k.irr_delta_pp < 0 ? 'text-red-400' : 'text-green-400'}`}>
                  {k.irr_delta_pp > 0 ? '+' : ''}{formatUiNumber(k.irr_delta_pp)}pp vs base
                </div>
                <div className="text-[10px] text-d-muted mt-0.5">{k.irr_driver}</div>
              </div>
            </div>

            {/* ── Row 2: Capex chart + IRR reforecast chart ── */}
            <div className="grid grid-cols-2 gap-4">
              {/* Capex actuals vs plan */}
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
                <div className="flex items-center justify-between mb-1">
                  <h2 className="text-sm font-semibold text-white">Capex actuals vs plan</h2>
                  <span className="text-[10px] text-d-muted bg-d-bg px-2 py-0.5 rounded">$0 million</span>
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={capexChartData} margin={{ top: 10, right: 10, left: -10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                    <XAxis dataKey="quarter" tick={{ fontSize: 9 }} />
                    <YAxis
                      tick={{ fontSize: 9 }}
                      tickFormatter={(value: number) =>
                        `$${formatUiNumber(value)}M`
                      }
                    />
                    <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} formatter={(v: number, name: string) => [`$${formatUiNumber(v)}M`, name]} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <defs>
                      <linearGradient id="planGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#94a3b8" stopOpacity={0.15} />
                        <stop offset="95%" stopColor="#94a3b8" stopOpacity={0.02} />
                      </linearGradient>
                      <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <Area type="monotone" dataKey="Plan" stroke="#94a3b8" strokeWidth={2}
                      strokeDasharray="8 4" fill="url(#planGrad)" dot={false}
                      connectNulls />
                    <Area type="monotone" dataKey="Actuals" stroke="#3b82f6" strokeWidth={2.5}
                      fill="url(#actualGrad)" dot={{ r: 3, fill: '#3b82f6' }}
                      connectNulls />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* IRR reforecast to complete */}
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
                <div className="flex items-center justify-between mb-1">
                  <h2 className="text-sm font-semibold text-white">IRR reforecast to complete</h2>
                  <span className="text-[10px] text-d-muted bg-d-bg px-2 py-0.5 rounded">quarterly</span>
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={irrChartData} margin={{ top: 10, right: 10, left: -10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                    <XAxis dataKey="quarter" tick={{ fontSize: 9 }} />
                    <YAxis
                      tick={{ fontSize: 9 }}
                      domain={['auto', 'auto']}
                      tickFormatter={(value: number) =>
                        `${formatUiNumber(value)}%`
                      }
                    />
                    <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} formatter={(v: number, name: string) => [`${formatUiNumber(v, { maximumFractionDigits: 2 })}%`, name]} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Line type="monotone" dataKey="IRR forecast" stroke="#3b82f6" strokeWidth={2.5}
                      dot={{ r: 4, fill: '#3b82f6', stroke: '#fff', strokeWidth: 2 }} />
                    <Line type="monotone" dataKey="Hurdle 10%" stroke="#f59e0b" strokeWidth={1.5}
                      strokeDasharray="8 4" dot={false} />
                    <Line type="monotone" dataKey="Base 12.3%" stroke="#94a3b8" strokeWidth={1.5}
                      strokeDasharray="4 4" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>


          </>
        ) : (
          <div className="flex items-center justify-center h-64 text-d-muted">
            {monLoading ? (
              <span className="animate-pulse text-sm">Loading monitor data...</span>
            ) : (
              <span className="text-sm">Click Refresh to load the performance monitor</span>
            )}
          </div>
        )}
      </div>
      <FloatingAssistant tabKey="monitor" pageContext="DSCR covenant monitor with traffic-light alerts, debt service waterfall, variance tracking" />
    </div>
  );
}
