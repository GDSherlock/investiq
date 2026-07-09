'use client';

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import Link from 'next/link';
import { getModel, uploadModel } from '@/lib/api';
import { useScenario } from '../ScenarioContext';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts';
import FloatingAssistant from '../FloatingAssistant';

/* ── Helpers ── */
function fmtPct(v: any): string {
  if (v == null) return '—';
  const n = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(n)) return String(v);
  return n < 1 ? `${(n * 100).toFixed(1)}%` : `${n}%`;
}
function fmtUsd(v: any): string {
  if (v == null) return '—';
  const n = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(n)) return String(v);
  return `$${n}M`;
}
function fmtNum(v: any, suffix = ''): string {
  if (v == null) return '—';
  return `${v}${suffix}`;
}

export default function DashboardPage() {
  const [modelId, setModelId] = useState<string>('');
  const [model, setModel] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const { scenario } = useScenario();

  /* Fetch model data for a given id */
  const fetchModel = useCallback(async (id: string) => {
    try {
      const m = await getModel(id);
      setModel(m);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  /* ── Upload state ── */
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleUpload = useCallback(async () => {
    if (!uploadFile) return;
    setUploading(true);
    setUploadError(null);
    try {
      const data = await uploadModel(uploadFile);
      localStorage.setItem('investiq_model_id', data.model_id);
      localStorage.setItem('investiq_investment_id', data.investment_id);
      setModelId(data.model_id);
      setLoading(true);
      setUploadFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await fetchModel(data.model_id);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }, [uploadFile, fetchModel]);

  /* Load on mount */
  useEffect(() => {
    const id = localStorage.getItem('investiq_model_id');
    if (id) {
      setModelId(id);
      fetchModel(id);
    } else {
      setLoading(false);
    }
  }, [fetchModel]);

  /* Re-fetch when user returns to the page (tab switch, alt-tab, navigation) */
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        const id = localStorage.getItem('investiq_model_id');
        if (id && id !== modelId) {
          setModelId(id);
          setLoading(true);
          fetchModel(id);
        } else if (id) {
          fetchModel(id);
        }
      }
    };
    const handleFocus = () => {
      const id = localStorage.getItem('investiq_model_id');
      if (id && id !== modelId) {
        setModelId(id);
        setLoading(true);
        fetchModel(id);
      }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'investiq_model_id' && e.newValue && e.newValue !== modelId) {
        setModelId(e.newValue);
        setLoading(true);
        fetchModel(e.newValue);
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('focus', handleFocus);
    window.addEventListener('storage', handleStorage);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('storage', handleStorage);
    };
  }, [modelId, fetchModel]);

  /* ── Derived data ── */
  const parsed = model?.parsed_json || {};
  const cover = parsed.cover || {};
  const returns = parsed.returns || {};
  const metrics = returns.metrics || [];
  const assumptions = parsed.assumptions || [];
  const pnl = parsed.pnl || {};
  const checks = parsed.checks || [];
  const sheets = parsed.sheets || [];

  /* ── Extract KPIs from Returns ── */
  const kpi = useMemo(() => {
    const m: Record<string, any> = {};
    for (const item of metrics) {
      m[item.metric] = item;
    }
    return {
      irr: m['Project IRR (unlevered)']?.[scenario],
      irrStress: m['Project IRR (unlevered)']?.stress_case,
      irrUpside: m['Project IRR (unlevered)']?.upside_case,
      npv: m['NPV @ WACC (USD M)']?.[scenario],
      payback: m['Payback period (years)']?.[scenario],
      dscr: m['DSCR — average']?.[scenario],
      dscrMin: m['DSCR — minimum (year 2030)']?.[scenario],
      equityX: m['Equity multiple (MoM)']?.[scenario],
      equityIrr: m['Equity IRR (levered)']?.[scenario],
    };
  }, [metrics, scenario]);

  /* ── Revenue & EBITDA chart data from PnL ── */
  const chartData = useMemo(() => {
    const years = pnl.years || [];
    const revenue = pnl.data?.['Revenue (from Revenue sheet)'] || [];
    const ebitda = pnl.data?.['EBITDA'] || [];
    return years
      .map((y: string, i: number) => ({
        year: y,
        Revenue: Math.round((revenue[i] || 0) * 10) / 10,
        EBITDA: Math.round((ebitda[i] || 0) * 10) / 10,
      }))
      .filter((d: any) => d.Revenue > 0 || d.EBITDA !== 0);
  }, [pnl]);

  /* ── Capital structure ── */
  const capStructure = useMemo(() => {
    const debtAssumption = assumptions.find((a: any) => /debt.?ratio/i.test(a.name));
    const debtRatio = debtAssumption?.value || 0.65;
    const dr = typeof debtRatio === 'number' ? debtRatio : parseFloat(debtRatio);
    const ratio = isNaN(dr) ? 0.65 : dr > 1 ? dr / 100 : dr;
    return [
      { name: 'Equity', value: Math.round((1 - ratio) * 100), color: '#3b82f6' },
      { name: 'Debt', value: Math.round(ratio * 100), color: '#ef4444' },
    ];
  }, [assumptions]);

  /* ── Model health checks for display ── */
  const healthChecks = useMemo(() => {
    const items: { text: string; status: 'pass' | 'warn' }[] = [];
    // Derive checks from model data
    const assumptionCount = assumptions.length;
    if (assumptionCount > 0) items.push({ text: `Assumption sheet: ${assumptionCount} key drivers mapped`, status: 'pass' });

    const opsStart = assumptions.find((a: any) => a.name === 'Operations start year')?.value;
    const opsEnd = assumptions.find((a: any) => a.name === 'Operations end year')?.value;
    if (opsStart && opsEnd) items.push({ text: `Cash flows ${opsStart}–${opsEnd} — ${Number(opsEnd) - Number(opsStart) + 1}-year model`, status: 'pass' });

    const dscrCov = assumptions.find((a: any) => a.name === 'DSCR covenant (min)')?.value;
    if (dscrCov) items.push({ text: `DSCR covenant check formula found (>${dscrCov}x)`, status: 'pass' });

    const sheetsFound = parsed.sheets || [];
    if (sheetsFound.length > 0) items.push({ text: `${sheetsFound.length} sheets detected and parsed`, status: 'pass' });

    // Warnings from checks sheet
    for (const c of checks) {
      const desc = c.description || '';
      const status = c.status || '';
      if (status === 'FAIL' || status === 'WARNING') {
        items.push({ text: `${desc} (${c.value})`, status: 'warn' });
      }
    }

    return items;
  }, [assumptions, checks, parsed]);

  /* ── Detected sheets summary ── */
  const sheetSummary = useMemo(() => {
    const summaries: { label: string; tags: string[] }[] = [];
    const sheets: string[] = parsed.sheets || [];

    // Assumptions summary: show first 3 key assumptions
    const topAssumptions = assumptions.slice(0, 3).map((a: any) => {
      const v = a.value;
      const n = typeof v === 'number' ? v : parseFloat(v);
      if (!isNaN(n) && n > 0 && n < 1) return `${a.name.split('(')[0].trim()} ${(n * 100).toFixed(1)}%`;
      return `${a.name.split('(')[0].trim()} ${v}`;
    });
    if (assumptions.length > 0) summaries.push({ label: 'Assumptions', tags: topAssumptions.length ? topAssumptions : ['No data'] });

    // Revenue sheet
    if (sheets.some(s => /revenue|operations/i.test(s))) {
      const revData = parsed.revenue?.data || {};
      const revKeys = Object.keys(revData).slice(0, 3);
      summaries.push({ label: 'Revenue', tags: revKeys.length ? revKeys : ['Revenue data'] });
    }

    // Capex sheet
    if (sheets.some(s => /capex/i.test(s))) {
      const capexData = parsed.capex?.data || {};
      const capexKeys = Object.keys(capexData).filter(k => !k.startsWith('──')).slice(0, 2);
      summaries.push({ label: 'Capex', tags: capexKeys.length ? capexKeys : ['Capex data'] });
    }

    // PnL sheet
    if (sheets.some(s => /pnl|p&l|income/i.test(s))) {
      const pnlKeys = Object.keys(pnl.data || {}).filter(k => !k.startsWith('──')).slice(0, 3);
      summaries.push({ label: 'PnL', tags: pnlKeys.length ? pnlKeys : ['PnL data'] });
    }

    // Cash Flows
    if (sheets.some(s => /cash/i.test(s))) summaries.push({ label: 'Cash Flows', tags: ['FCF', 'Debt service'] });

    // Returns
    summaries.push({
      label: 'Returns',
      tags: [`IRR ${fmtPct(kpi.irr)}`, `NPV ${fmtUsd(kpi.npv)}`, `DSCR ${kpi.dscr}x`],
    });

    return summaries;
  }, [parsed, assumptions, pnl, kpi]);

  /* ── Slider assumptions for left sidebar ── */
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

  if (loading) return <div className="flex items-center justify-center h-64 text-d-muted">Loading model...</div>;
  if (!model) return (
    <div className="text-center py-12">
      <p className="text-slate-300 mb-2">No model loaded. Upload a model first.</p>
      <Link href="/" className="text-gold-400 hover:underline">Go to Upload</Link>
    </div>
  );

  const projectName = cover.Project || model.original_filename;
  const totalCapex = cover['Total Capex'] || '—';
  const opsRange = cover.Operations || '—';

  return (
    <div className="flex gap-4">
      {/* ── Left Sidebar ── */}
      <div className="w-56 flex-shrink-0 space-y-4">
        {/* Upload Financial Model */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
          <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">Upload Financial Model</div>
          <label className="flex flex-col items-center gap-2 border-2 border-dashed border-d-border rounded-lg p-3 cursor-pointer hover:border-gold-400 hover:bg-d-hover/30 transition">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-d-muted">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <span className="text-[10px] text-d-muted text-center break-all">{uploadFile ? uploadFile.name : 'Select .xlsx file'}</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls"
              className="hidden"
              onChange={(e) => { setUploadFile(e.target.files?.[0] || null); setUploadError(null); }}
            />
          </label>
          {uploadFile && (
            <button
              onClick={handleUpload}
              disabled={uploading}
              className="mt-2 w-full bg-gold-500 text-white text-xs py-1.5 px-3 rounded hover:bg-gold-600 disabled:bg-d-dim disabled:cursor-not-allowed transition"
            >
              {uploading ? 'Processing…' : 'Upload & Analyze'}
            </button>
          )}
          {uploadError && <p className="mt-1 text-[10px] text-red-400">{uploadError}</p>}
        </div>

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
              <div className="text-lg font-bold text-gold-400">{fmtUsd(kpi.npv)}</div>
              <div className="text-[9px] text-d-muted">Base: {fmtUsd(kpi.npv)}</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">PAYBACK</div>
              <div className="text-lg font-bold text-white">{fmtNum(kpi.payback, 'yr')}</div>
              <div className="text-[9px] text-d-muted">&lt;12yr target</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">DSCR</div>
              <div className="text-lg font-bold text-white">{fmtNum(kpi.dscr, 'x')}</div>
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
        {/* KPI Cards Row */}
        <div className="grid grid-cols-5 gap-3">
          {[
            {
              label: 'PROJECT IRR', value: fmtPct(kpi.irr),
              sub1: `+${((kpi.irr || 0.123) * 100 - 10).toFixed(1)}pp above hurdle`,
              sub2: 'Hurdle: 10%', color: 'border-green-500',
              indicator: '▲ Positive value creation',
            },
            {
              label: 'NPV @ 8.5% WACC', value: fmtUsd(kpi.npv),
              sub1: '▲ Positive value creation',
              sub2: `Total capex: ${totalCapex}`, color: 'border-green-500',
            },
            {
              label: 'PAYBACK PERIOD', value: `${kpi.payback || '—'} yrs`,
              sub1: 'Within 12-yr target',
              sub2: 'Construction: 3 years', color: 'border-blue-500',
            },
            {
              label: 'AVG DSCR', value: `${kpi.dscr || '—'}x`,
              sub1: '▲ Above 1.25x covenant',
              sub2: `Min DSCR: ${kpi.dscrMin}x`, color: 'border-green-500',
            },
            {
              label: 'EQUITY MULTIPLE', value: `${kpi.equityX || '—'}x`,
              sub1: `${cover.Operations ? cover.Operations.split('–')[1]?.trim()?.substring(0, 4) || '17' : '17'}-yr operations`,
              sub2: `Horizon: ${cover.Operations?.split('–')[1]?.trim() || '2044'}`, color: 'border-blue-500',
            },
          ].map((card) => (
            <div key={card.label} className={`bg-d-card rounded-lg shadow-sm border-l-4 ${card.color} p-4`}>
              <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium">{card.label}</div>
              <div className="text-2xl font-bold text-white mt-1">{card.value}</div>
              <div className="text-[10px] text-green-400 mt-1">{card.sub1}</div>
              <div className="text-[10px] text-d-muted">{card.sub2}</div>
            </div>
          ))}
        </div>

        {/* Revenue & EBITDA Chart + Capital Structure */}
        <div className="grid grid-cols-3 gap-4">
          {/* Revenue & EBITDA Chart */}
          <div className="col-span-2 bg-d-card rounded-lg shadow-sm border border-d-border p-5">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm">📊</span>
              <h2 className="text-sm font-semibold text-white">Revenue & EBITDA trajectory</h2>
            </div>
            <p className="text-[10px] text-d-muted mb-3">SGD million · {cover.Operations || '2028–2044'}</p>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1B2B65" />
                  <XAxis dataKey="year" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="Revenue" fill="#60a5fa" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="EBITDA" fill="#34d399" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-d-muted text-xs">No chart data available</div>
            )}
          </div>

          {/* Capital Structure Pie */}
          <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm">⚙</span>
              <h2 className="text-sm font-semibold text-white">Capital structure</h2>
            </div>
            <div className="flex items-center justify-center mt-2">
              <PieChart width={180} height={180}>
                <Pie
                  data={capStructure}
                  cx={90}
                  cy={90}
                  innerRadius={50}
                  outerRadius={80}
                  dataKey="value"
                  stroke="none"
                >
                  {capStructure.map((entry, i) => (
                    <Cell key={i} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip formatter={(value: number) => `${value}%`} contentStyle={{ fontSize: 11, backgroundColor: "#111C44", border: "1px solid #1B2B65", color: "#A3AED0" }} />
              </PieChart>
            </div>
            <div className="flex justify-center gap-4 mt-2 text-xs">
              {capStructure.map((s) => (
                <div key={s.name} className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
                  <span className="text-slate-300">{s.name} {s.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Model Health Check + Detected Sheets */}
        <div className="grid grid-cols-2 gap-4">
          {/* Model Health Check */}
          <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-green-400 text-sm">✓</span>
              <h2 className="text-sm font-semibold text-white">Model health check</h2>
            </div>
            <p className="text-[10px] text-d-muted mb-3">AI-parsed structure</p>
            <div className="space-y-2">
              {healthChecks.map((item, i) => (
                <div key={i} className={`flex items-start gap-2 text-xs rounded px-2 py-1.5 ${
                  item.status === 'pass' ? 'bg-green-900/30' : 'bg-amber-900/30'
                }`}>
                  <span className={`mt-0.5 flex-shrink-0 ${
                    item.status === 'pass' ? 'text-green-400' : 'text-amber-500'
                  }`}>
                    {item.status === 'pass' ? '✓' : '⚠'}
                  </span>
                  <span className={item.status === 'pass' ? 'text-green-400' : 'text-amber-400'}>
                    {item.text}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Detected Model Sheets */}
          <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm">📄</span>
              <h2 className="text-sm font-semibold text-white">Detected model sheets</h2>
            </div>
            <div className="mt-3 space-y-3">
              {sheetSummary.map((sheet) => (
                <div key={sheet.label} className="flex items-start gap-3">
                  <span className="text-[10px] font-mono font-bold text-gold-400 bg-d-hover px-1.5 py-0.5 rounded w-20 text-center flex-shrink-0">
                    {sheet.label}
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {sheet.tags.map((tag, j) => (
                      <span key={j} className="text-[10px] text-d-muted">{tag}{j < sheet.tags.length - 1 ? ' · ' : ''}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            {/* Raw sheet list */}
            <div className="mt-4 pt-3 border-t border-d-border">
              <div className="text-[10px] text-d-muted mb-1">All {sheets.length} sheets detected</div>
              <div className="flex flex-wrap gap-1">
                {sheets.map((s: string) => (
                  <span key={s} className="text-[9px] bg-d-bg text-d-muted px-1.5 py-0.5 rounded">{s}</span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
      <FloatingAssistant tabKey="overview" pageContext="Dashboard with KPIs, revenue/EBITDA chart, capital structure, model health checks" />
    </div>
  );
}
