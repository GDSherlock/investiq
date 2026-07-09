'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import Link from 'next/link';
import { getModel, createScenario, getCashFlows } from '@/lib/api';
import { usePersona } from '../PersonaContext';
import { useScenario } from '../ScenarioContext';
import FloatingAssistant from '../FloatingAssistant';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  LineChart, Line, AreaChart, Area, Cell, ReferenceLine,
} from 'recharts';

/* ── Helpers ── */
function fmtPct(v: any): string {
  if (v == null) return '—';
  const n = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(n)) return String(v);
  return n < 1 ? `${(n * 100).toFixed(1)}%` : `${n.toFixed(2)}%`;
}

export default function CashFlowsPage() {
  const [modelId, setModelId] = useState('');
  const [model, setModel] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [cfLoading, setCfLoading] = useState(false);
  const [cfData, setCfData] = useState<any>(null);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const { persona } = usePersona();
  const { scenario } = useScenario();

  /* ── Load model ── */
  const fetchModel = useCallback(async (id: string) => {
    try {
      const m = await getModel(id);
      setModel(m);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    const id = localStorage.getItem('investiq_model_id');
    if (id) { setModelId(id); fetchModel(id); }
    else setLoading(false);
  }, [fetchModel]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        const id = localStorage.getItem('investiq_model_id');
        if (id && id !== modelId) { setModelId(id); setLoading(true); setCfData(null); setShowAnalysis(false); fetchModel(id); }
      }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'investiq_model_id' && e.newValue && e.newValue !== modelId) {
        setModelId(e.newValue); setLoading(true); setCfData(null); setShowAnalysis(false); fetchModel(e.newValue);
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('storage', handleStorage);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('storage', handleStorage);
    };
  }, [modelId, fetchModel]);

  /* ── Interpret Cash Flows (auto-load charts) ── */
  const loadCashFlows = useCallback(async () => {
    if (!modelId) return;
    setCfLoading(true);
    try {
      const scenarioObj = await createScenario(modelId, 'Cash Flow Analysis', { scenario });
      const data = await getCashFlows(scenarioObj.id);
      setCfData(data);
    } catch (e) { console.error(e); }
    setCfLoading(false);
  }, [modelId, scenario]);

  /* "Interpret Cash Flows" button — shows the AI analysis panel */
  const interpretCashFlows = useCallback(async () => {
    if (!cfData) await loadCashFlows();
    setShowAnalysis(true);
    try { sessionStorage.setItem(`investiq_cf_analysis_${modelId}`, '1'); } catch {}
  }, [cfData, loadCashFlows, modelId]);

  /* Auto-load chart data on model ready */
  useEffect(() => {
    if (model && !cfLoading) loadCashFlows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, scenario]);

  /* Restore analysis visibility from sessionStorage */
  useEffect(() => {
    if (modelId) {
      try {
        const saved = sessionStorage.getItem(`investiq_cf_analysis_${modelId}`);
        if (saved === '1') setShowAnalysis(true);
      } catch {}
    }
  }, [modelId]);

  /* ── Derived sidebar data ── */
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
        formatted = `${(n * 100).toFixed(1)}%`;
      } else if (a.unit === '$/MMBtu' || a.unit === '$') {
        formatted = `$${n}`;
      } else {
        formatted = String(n);
      }
      return { label: a.name, value: formatted };
    }).slice(0, 12);
  }, [assumptions]);

  /* ── Chart data ── */
  const fcfChartData = useMemo(() => {
    if (!cfData) return [];
    return (cfData.years || []).map((yr: string, i: number) => ({
      year: yr,
      fcf: cfData.fcf?.[i] ?? 0,
    }));
  }, [cfData]);

  const p10p50p90Data = useMemo(() => {
    if (!cfData) return [];
    return (cfData.years || []).map((yr: string, i: number) => ({
      year: yr,
      P90: cfData.cum_p90?.[i] ?? 0,
      P50: cfData.cum_p50?.[i] ?? 0,
      P10: cfData.cum_p10?.[i] ?? 0,
    })).filter((_: any, i: number) => {
      const yr = parseInt(cfData.years[i]);
      return yr >= parseInt(cfData.years[0]) + 3; // ops years only
    });
  }, [cfData]);

  const dscrChartData = useMemo(() => {
    if (!cfData) return [];
    return (cfData.years || []).map((yr: string, i: number) => ({
      year: yr,
      DSCR: cfData.dscr?.[i] ?? null,
      Covenant: cfData.dscr_covenant ?? 1.25,
    })).filter((d: any) => d.DSCR !== null);
  }, [cfData]);

  const cumFcfData = useMemo(() => {
    if (!cfData) return [];
    return (cfData.years || []).map((yr: string, i: number) => ({
      year: yr,
      cumFCF: cfData.cumulative_fcf?.[i] ?? 0,
    }));
  }, [cfData]);

  if (loading) return <div className="flex items-center justify-center h-64 text-d-muted">Loading model...</div>;
  if (!model) return (
    <div className="text-center py-12">
      <p className="text-slate-300 mb-2">No model loaded. Upload a model first.</p>
      <Link href="/" className="text-gold-400 hover:underline">Go to Upload</Link>
    </div>
  );

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
                <span className="text-lg">📊</span>
                <h1 className="text-lg font-semibold text-white">Cash flow simulator</h1>
              </div>
              <p className="text-xs text-d-muted mt-1">
                P10/P50/P90 · DSCR covenant · Payback tracking
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={interpretCashFlows}
                disabled={cfLoading}
                className="bg-gold-500 hover:bg-gold-600 text-white text-sm font-semibold
                  px-4 py-2 rounded-lg transition disabled:bg-d-dim flex items-center gap-1.5"
              >
                {cfLoading ? (
                  <span className="animate-pulse">Loading...</span>
                ) : (
                  <>▶ Interpret Cash Flows</>
                )}
              </button>
            </div>
          </div>
        </div>

        {cfData ? (
          <>
            {/* ── Row 1: FCF Bar Chart + P10/P50/P90 Line Chart ── */}
            <div className="grid grid-cols-2 gap-4">
              {/* Annual Free Cash Flow */}
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
                <div className="flex items-center justify-between mb-1">
                  <h2 className="text-sm font-semibold text-white">Annual free cash flow</h2>
                  <span className="text-[10px] text-d-muted bg-d-bg px-2 py-0.5 rounded">$M million</span>
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={fcfChartData} margin={{ top: 10, right: 10, left: -10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                    <XAxis dataKey="year" tick={{ fontSize: 9 }} />
                    <YAxis tick={{ fontSize: 9 }} />
                    <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} formatter={(v: number) => [`$${v}M`, 'FCF']} />
                    <ReferenceLine y={0} stroke="#94a3b8" strokeWidth={1} />
                    <Bar dataKey="fcf" radius={[2, 2, 0, 0]}>
                      {fcfChartData.map((entry: any, i: number) => (
                        <Cell key={i} fill={entry.fcf >= 0 ? '#34d399' : '#f87171'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* P10/P50/P90 Distribution */}
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
                <div className="flex items-center justify-between mb-1">
                  <h2 className="text-sm font-semibold text-white">P10 / P50 / P90 distribution</h2>
                  <span className="text-[10px] text-d-muted bg-d-bg px-2 py-0.5 rounded">Monte Carlo</span>
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={p10p50p90Data} margin={{ top: 10, right: 10, left: -10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                    <XAxis dataKey="year" tick={{ fontSize: 9 }} />
                    <YAxis tick={{ fontSize: 9 }} />
                    <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} formatter={(v: number) => [`$${v}M`]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="P90" stroke="#22c55e" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="P50" stroke="#3b82f6" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="P10" stroke="#f87171" strokeWidth={2} dot={false} strokeDasharray="5 3" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* ── Row 2: NPV Distribution + DSCR vs Covenant + Cumulative FCF ── */}
            <div className="grid grid-cols-3 gap-4">
              {/* NPV Distribution */}
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
                <h2 className="text-sm font-semibold text-white mb-3">NPV distribution</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={cfData.npv_distribution} margin={{ top: 5, right: 5, left: -15, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                    <XAxis dataKey="label" tick={{ fontSize: 9 }} />
                    <YAxis tick={{ fontSize: 9 }} />
                    <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} />
                    <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                      {(cfData.npv_distribution || []).map((entry: any, i: number) => {
                        const isHighlight = entry.label.startsWith('$');
                        return <Cell key={i} fill={isHighlight ? '#818cf8' : '#60a5fa'} />;
                      })}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* DSCR by Year vs Covenant */}
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
                <h2 className="text-sm font-semibold text-white mb-3">DSCR by year vs covenant</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={dscrChartData} margin={{ top: 5, right: 10, left: -15, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                    <XAxis dataKey="year" tick={{ fontSize: 9 }} />
                    <YAxis tick={{ fontSize: 9 }} domain={['auto', 'auto']} />
                    <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} formatter={(v: number, name: string) => [v.toFixed(2) + 'x', name]} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Line type="monotone" dataKey="DSCR" stroke="#22c55e" strokeWidth={2} dot={{ r: 3, fill: '#22c55e' }} />
                    <Line type="monotone" dataKey="Covenant" stroke="#f59e0b" strokeWidth={2} strokeDasharray="8 4" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Cumulative Cash Flow */}
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
                <h2 className="text-sm font-semibold text-white mb-3">Cumulative cash flow</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={cumFcfData} margin={{ top: 5, right: 10, left: -15, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                    <XAxis dataKey="year" tick={{ fontSize: 9 }} />
                    <YAxis tick={{ fontSize: 9 }} />
                    <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} formatter={(v: number) => [`$${v}M`, 'Cumulative']} />
                    <ReferenceLine y={0} stroke="#94a3b8" strokeWidth={1} />
                    <defs>
                      <linearGradient id="cumGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <Area type="monotone" dataKey="cumFCF" stroke="#3b82f6" strokeWidth={2} fill="url(#cumGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* ── Cash Flow Analysis Panel ── */}
            {showAnalysis && cfData.analysis && (
              <div className="bg-gradient-to-r from-navy-700 to-navy-800 rounded-lg p-5 text-white">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">💡</span>
                    <h2 className="text-sm font-bold">Cash Flow Analysis</h2>
                  </div>
                  <span className="text-[10px] bg-white/20 px-2 py-0.5 rounded">{persona.name}</span>
                </div>
                <div className="grid grid-cols-3 gap-6">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider font-bold text-gold-300 mb-2">Profile Verdict</div>
                    <p className="text-xs leading-relaxed text-white/90">{cfData.analysis.profile_verdict}</p>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider font-bold text-gold-300 mb-2">Risk Period</div>
                    <p className="text-xs leading-relaxed text-white/90">{cfData.analysis.risk_period}</p>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider font-bold text-gold-300 mb-2">Monitor This</div>
                    <p className="text-xs leading-relaxed text-white/90">{cfData.analysis.monitor_this}</p>
                  </div>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="flex items-center justify-center h-64 text-d-muted">
            {cfLoading ? (
              <span className="animate-pulse text-sm">Loading cash flow data...</span>
            ) : (
              <span className="text-sm">Loading model data...</span>
            )}
          </div>
        )}
      </div>
      <FloatingAssistant tabKey="cash_flow" pageContext="Cash flow simulator with annual FCF chart, P10/P50/P90 bands, NPV distribution, DSCR covenant chart, cumulative cash flow" />
    </div>
  );
}
