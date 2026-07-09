'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import Link from 'next/link';
import { getModel, createScenario, runMonteCarlo } from '@/lib/api';
import { useScenario } from '../ScenarioContext';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import FloatingAssistant from '../FloatingAssistant';

/* ── Helpers ── */
function fmtPct(v: any): string {
  if (v == null) return '—';
  const n = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(n)) return String(v);
  return n < 1 ? `${(n * 100).toFixed(1)}%` : `${n.toFixed(2)}%`;
}

/* ── MC variable config ── */
interface MCVar {
  key: string;
  label: string;
  unit: string;
  defaultStd: number;
  defaultCorr: number;
  fmt: (v: number) => string;
  pctInput?: boolean;
}

/* Known mapping: sensitivity labels → assumption keys */
const SENS_TO_ASSUMPTION: Record<string, string> = {
  'Throughput fee ($/MMBtu)': 'Regasification fee (base)',
  'Utilisation rate': 'Terminal utilisation — Steady',
  'WACC': 'WACC (unlevered)',
  'Gas demand growth': 'Revenue growth rate (annual)',
  'Carbon tax ($/tonne)': 'Carbon tax — Singapore ($/tonne)',
  'Capex overrun': 'Capex contingency %',
  'Opex inflation rate': 'Opex inflation rate',
  'Debt ratio': 'Debt ratio',
};

function buildMCVarDefs(sensitivity: any, assumptions: any[]): MCVar[] {
  const oneWay: any[] = sensitivity?.one_way ?? [];
  if (oneWay.length === 0) return [];

  const assumptionMap: Record<string, any> = {};
  for (const a of assumptions) assumptionMap[a.name] = a;

  const defs: MCVar[] = [];
  for (const item of oneWay) {
    const sensLabel = item.assumption;
    const assumptionKey = SENS_TO_ASSUMPTION[sensLabel] || sensLabel;
    const assumption = assumptionMap[assumptionKey];
    if (!assumption) continue;

    const baseVal = parseFloat(assumption.value);
    if (isNaN(baseVal)) continue;

    const isPct = baseVal > 0 && baseVal < 1;
    defs.push({
      key: assumptionKey,
      label: sensLabel,
      unit: isPct ? '%' : (assumption.unit || '$'),
      defaultStd: isPct ? baseVal * 100 * 0.1 : baseVal * 0.1,
      defaultCorr: 0.0,
      fmt: isPct ? (v: number) => v.toFixed(1) : (v: number) => v.toFixed(2),
      pctInput: isPct,
    });
  }
  return defs;
}

interface MCVarState {
  mean: number;
  stdDev: number;
  corr: number;
}

export default function MonteCarloPage() {
  const [modelId, setModelId] = useState('');
  const [model, setModel] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [nTrials, setNTrials] = useState(5000);
  const [result, setResult] = useState<any>(null);
  const { scenario } = useScenario();

  /* Variable state: key → { mean, stdDev, corr } */
  const [vars, setVars] = useState<Record<string, MCVarState>>({});
  const [mcVarDefs, setMcVarDefs] = useState<MCVar[]>([]);

  /* ── Load model ── */
  const fetchModel = useCallback(async (id: string) => {
    try {
      const m = await getModel(id);
      setModel(m);

      const assumptions: any[] = m.parsed_json?.assumptions ?? [];
      const sensitivity = m.parsed_json?.sensitivity ?? {};
      const defs = buildMCVarDefs(sensitivity, assumptions);
      setMcVarDefs(defs);

      const init: Record<string, MCVarState> = {};
      for (const def of defs) {
        const found = assumptions.find((a: any) => a.name === def.key);
        const rawVal = found?.value != null ? parseFloat(found.value) : 0;
        const displayMean = def.pctInput ? rawVal * 100 : rawVal;
        init[def.key] = {
          mean: displayMean,
          stdDev: def.defaultStd,
          corr: def.defaultCorr,
        };
      }
      setVars(init);
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
        if (id && id !== modelId) { setModelId(id); setLoading(true); setResult(null); fetchModel(id); }
      }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'investiq_model_id' && e.newValue && e.newValue !== modelId) {
        setModelId(e.newValue); setLoading(true); setResult(null); fetchModel(e.newValue);
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('storage', handleStorage);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('storage', handleStorage);
    };
  }, [modelId, fetchModel]);

  /* ── Run simulation ── */
  const runSim = async () => {
    if (!modelId) return;
    setRunning(true);
    try {
      const scenarioObj = await createScenario(modelId, 'Monte Carlo', { scenario });
      const variables: Record<string, number> = {};
      const volatilities: Record<string, number> = {};
      for (const def of mcVarDefs) {
        const v = vars[def.key];
        if (!v) continue;
        variables[def.key] = def.pctInput ? v.mean / 100 : v.mean;
        volatilities[def.key] = def.pctInput ? v.stdDev / 100 : v.stdDev;
      }
      const data = await runMonteCarlo(scenarioObj.id, nTrials, variables, volatilities);
      setResult(data);
    } catch (e) { console.error(e); }
    setRunning(false);
  };

  // Re-run simulation when scenario changes
  useEffect(() => {
    if (modelId && result) runSim();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario]);

  const mc = result?.result;

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

  const updateVar = (key: string, field: keyof MCVarState, value: number) => {
    setVars(prev => ({ ...prev, [key]: { ...prev[key], [field]: value } }));
  };

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
              <div className="text-[9px] text-d-muted">Base: ${kpi.npv}M</div>
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
        {/* Header — trials input + run button inline */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🎲</span>
              <h1 className="text-lg font-semibold text-white">Monte Carlo simulation engine</h1>
            </div>
            <div className="flex items-center gap-3">
              <label className="text-xs text-d-muted">Trials:</label>
              <input
                type="number"
                value={nTrials}
                onChange={e => setNTrials(Math.max(100, Math.min(50000, Number(e.target.value))))}
                min={100}
                max={50000}
                step={1000}
                className="bg-sky-900/40 border border-d-border rounded px-2 py-1 w-24 text-sm text-right text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
              />
              <button
                onClick={runSim}
                disabled={!modelId || running}
                className="px-5 py-1.5 rounded-lg text-white font-semibold text-sm
                  bg-gold-500 hover:bg-gold-600
                  disabled:bg-d-dim disabled:cursor-not-allowed transition-all shadow-md whitespace-nowrap"
              >
                {running ? (
                  <span className="animate-pulse">Running...</span>
                ) : (
                  <>🎲 Run Monte Carlo</>
                )}
              </button>
            </div>
          </div>
          <p className="text-xs text-d-muted mt-1">
            Configure distributions per variable — engine runs {nTrials.toLocaleString()} trials and reports IRR, NPV, and probability of hurdle breach
          </p>
        </div>

        {/* Two-column layout: parameters left, results right */}
        <div className="flex gap-4">

          {/* ── Left column: compact parameter cards ── */}
          <div className="w-72 flex-shrink-0 space-y-2">
            {mcVarDefs.map((def) => {
              const v = vars[def.key];
              if (!v) return null;
              return (
                <div key={def.key} className="bg-d-card rounded-lg shadow-sm border border-d-border p-3">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-semibold text-white truncate" title={def.label}>{def.label}</h3>
                    <span className="text-[8px] px-1 py-0.5 rounded bg-green-900/30 text-green-400 font-medium uppercase">normal</span>
                  </div>
                  <div className="grid grid-cols-3 gap-1.5">
                    <div>
                      <label className="text-[9px] text-d-muted block mb-0.5">
                        Mean {def.pctInput ? '%' : def.unit}
                      </label>
                      <input
                        type="number"
                        value={v.mean}
                        onChange={e => updateVar(def.key, 'mean', Number(e.target.value))}
                        step={def.pctInput ? 0.1 : 0.01}
                        className="w-full bg-sky-900/40 border border-d-border rounded px-1.5 py-1 text-xs font-mono text-center text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
                      />
                    </div>
                    <div>
                      <label className="text-[9px] text-d-muted block mb-0.5">Std dev</label>
                      <input
                        type="number"
                        value={v.stdDev}
                        onChange={e => updateVar(def.key, 'stdDev', Number(e.target.value))}
                        step={def.pctInput ? 0.1 : 0.01}
                        min={0}
                        className="w-full bg-sky-900/40 border border-d-border rounded px-1.5 py-1 text-xs font-mono text-center text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
                      />
                    </div>
                    <div>
                      <label className="text-[9px] text-d-muted block mb-0.5">Corr</label>
                      <input
                        type="number"
                        value={v.corr}
                        onChange={e => updateVar(def.key, 'corr', Math.max(-1, Math.min(1, Number(e.target.value))))}
                        step={0.05}
                        min={-1}
                        max={1}
                        className="w-full bg-sky-900/40 border border-d-border rounded px-1.5 py-1 text-xs font-mono text-center text-white focus:outline-none focus:ring-1 focus:ring-gold-400"
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* ── Right column: results ── */}
          <div className="flex-1 space-y-3">
            {!mc && (
              <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-12 text-center">
                <div className="text-3xl mb-3">🎲</div>
                <p className="text-sm text-d-muted">Configure parameters and click <strong className="text-gold-400">Run Monte Carlo</strong> to see results</p>
              </div>
            )}

            {mc && (
              <>
                {/* KPI Cards — Row 1 */}
                <div className="grid grid-cols-4 gap-2">
                  {[
                    {
                      label: 'P10 IRR', value: `${mc.irr.p10}%`, color: 'text-red-500',
                      sub: `Pessimistic`,
                    },
                    {
                      label: 'P50 IRR', value: `${mc.irr.p50}%`, color: 'text-green-400',
                      sub: `Median`,
                    },
                    {
                      label: 'P90 IRR', value: `${mc.irr.p90}%`, color: 'text-green-400',
                      sub: `Optimistic`,
                    },
                    {
                      label: 'PROB > HURDLE', value: `${mc.prob_above_hurdle}%`, color: 'text-green-400',
                      sub: `P(IRR>10%)`,
                    },
                  ].map((card) => (
                    <div key={card.label} className="bg-d-card rounded-lg shadow-sm border border-d-border p-3 text-center">
                      <div className="text-[9px] text-d-muted uppercase tracking-wider font-medium">{card.label}</div>
                      <div className={`text-xl font-bold mt-1 ${card.color}`}>{card.value}</div>
                      <div className="text-[9px] text-d-muted mt-0.5">{card.sub}</div>
                    </div>
                  ))}
                </div>

                {/* KPI Cards — Row 2 */}
                <div className="grid grid-cols-4 gap-2">
                  {[
                    {
                      label: 'MEAN IRR', value: `${mc.irr.mean}%`,
                      sub: `σ ${mc.irr.std_dev}pp`,
                    },
                    {
                      label: 'P(NPV > 0)', value: `${mc.prob_npv_positive}%`,
                      sub: `Value creation`,
                    },
                    {
                      label: 'IRR RANGE', value: `${mc.irr_range_pp}pp`,
                      sub: `P10–P90`,
                    },
                    {
                      label: 'P50 NPV', value: `$${mc.npv.p50}M`,
                      sub: `P10 $${mc.npv.p10}M`,
                    },
                  ].map((card) => (
                    <div key={card.label} className="bg-d-card rounded-lg shadow-sm border border-d-border p-3 text-center">
                      <div className="text-[9px] text-d-muted uppercase tracking-wider font-medium">{card.label}</div>
                      <div className="text-xl font-bold text-white mt-1">{card.value}</div>
                      <div className="text-[9px] text-d-muted mt-0.5">{card.sub}</div>
                    </div>
                  ))}
                </div>

                {/* Simulation Insights */}
                <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg px-3 py-2">
                  <div className="text-[9px] font-semibold text-amber-400 uppercase tracking-wider">Simulation Insights</div>
                  <div className="mt-1 text-xs text-amber-300 space-y-0.5">
                    <p>• Mean IRR ({mc.irr.mean}%) is {mc.irr.mean > 10 ? 'above' : 'below'} the 10% hurdle rate with {mc.prob_above_hurdle}% probability.</p>
                    <p>• IRR spread (P10–P90) is {mc.irr_range_pp}pp — {Number(mc.irr_range_pp) < 2 ? 'low uncertainty' : Number(mc.irr_range_pp) < 4 ? 'moderate uncertainty' : 'high uncertainty'}.</p>
                    <p>• Throughput fee is the dominant risk driver (corr = {vars['Regasification fee (base)']?.corr ?? 1.0}).</p>
                    {mc.prob_npv_positive >= 99 && <p>• NPV is positive in {mc.prob_npv_positive}% of scenarios — strong value creation signal.</p>}
                  </div>
                </div>

                {/* Distribution Charts */}
                <div className="grid grid-cols-2 gap-3">
                  {/* IRR Distribution */}
                  <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
                    <div className="flex items-center justify-between mb-1">
                      <h2 className="text-xs font-semibold text-white">
                        IRR distribution — {mc.n_simulations.toLocaleString()} trials
                      </h2>
                      <span className="text-[9px] text-d-muted bg-d-bg px-1.5 py-0.5 rounded">density</span>
                    </div>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={mc.irr_histogram} margin={{ top: 10, right: 10, left: -15, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                        <XAxis
                          dataKey="bin_low"
                          tick={{ fontSize: 10 }}
                          tickFormatter={(v: number) => `${v.toFixed(1)}`}
                          interval={Math.max(0, Math.floor(mc.irr_histogram.length / 7) - 1)}
                        />
                        <YAxis tick={{ fontSize: 10 }} />
                        <Tooltip
                          contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }}
                          formatter={(value: number) => [value, 'Count']}
                          labelFormatter={(label: number) => `IRR: ${label.toFixed(1)}%`}
                        />
                        <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                          {mc.irr_histogram.map((entry: any, i: number) => {
                            const mid = (entry.bin_low + entry.bin_high) / 2;
                            let color = '#60a5fa';
                            if (mid < mc.irr.p10) color = '#f87171';
                            else if (mid > mc.irr.p90) color = '#34d399';
                            return <Cell key={i} fill={color} />;
                          })}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  {/* NPV Distribution */}
                  <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
                    <div className="flex items-center justify-between mb-1">
                      <h2 className="text-xs font-semibold text-white">NPV distribution</h2>
                      <span className="text-[9px] text-d-muted bg-d-bg px-1.5 py-0.5 rounded">$M</span>
                    </div>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={mc.npv_histogram} margin={{ top: 10, right: 10, left: -15, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                        <XAxis
                          dataKey="bin_low"
                          tick={{ fontSize: 10 }}
                          tickFormatter={(v: number) => `$${v.toFixed(0)}M`}
                          interval={Math.max(0, Math.floor(mc.npv_histogram.length / 7) - 1)}
                        />
                        <YAxis tick={{ fontSize: 10 }} />
                        <Tooltip
                          contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }}
                          formatter={(value: number) => [value, 'Count']}
                          labelFormatter={(label: number) => `NPV: $${label.toFixed(0)}M`}
                        />
                        <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                          {mc.npv_histogram.map((entry: any, i: number) => {
                            const mid = (entry.bin_low + entry.bin_high) / 2;
                            const distFromP50 = Math.abs(mid - mc.npv.p50);
                            const range = mc.npv.p90 - mc.npv.p10;
                            if (distFromP50 < range * 0.15) return <Cell key={i} fill="#818cf8" />;
                            if (mid < mc.npv.p10) return <Cell key={i} fill="#93c5fd" />;
                            return <Cell key={i} fill="#60a5fa" />;
                          })}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                    <div className="text-center -mt-2">
                      <span className="text-[9px] text-d-muted">
                        P50: <span className="font-semibold text-white">${mc.npv.p50}M</span>
                        {' · '}P10: ${mc.npv.p10}M · P90: ${mc.npv.p90}M
                      </span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>

        </div>
      </div>
      <FloatingAssistant tabKey="monte_carlo" pageContext="Monte Carlo simulation engine with configurable distributions, IRR/NPV histograms, probability of hurdle breach" />
    </div>
  );
}
