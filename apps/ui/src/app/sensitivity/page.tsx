'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import Link from 'next/link';
import { getModel } from '@/lib/api';
import { useScenario } from '../ScenarioContext';
import FloatingAssistant from '../FloatingAssistant';

/* ═══════════════════════════════════════════
   Types
   ═══════════════════════════════════════════ */

interface SensVariable {
  id: string;
  name: string;
  points: [number, number][];   // [[stress%, irr_decimal], …]
  display: DisplayMeta;
  category: 'revenue' | 'cost' | 'neutral';
}

interface DisplayMeta {
  type: 'actual' | 'stress';
  baseValue: number;
  prefix: string;
  suffix: string;
  decimals: number;
}

interface SensModel {
  baseIrr: number;       // decimal (e.g. 0.123)
  baseNpv: number;
  basePayback: number;
  baseDscr: number;
  baseEquityX: number;
  variables: SensVariable[];
  twoWay: any;
}

interface TornadoRow {
  name: string;
  low: number;   // IRR %
  high: number;  // IRR %
  impact: number;
}

/* ═══════════════════════════════════════════
   Constants
   ═══════════════════════════════════════════ */

const REVENUE_LABELS = new Set([
  'Throughput fee ($/MMBtu)', 'Utilisation rate', 'Gas demand growth',
]);
const COST_LABELS = new Set([
  'Carbon tax ($/tonne)', 'Capex overrun', 'Opex inflation rate',
]);

/* ═══════════════════════════════════════════
   Interpolation (matches Python script)
   ═══════════════════════════════════════════ */

function interp(points: [number, number][], x: number): number {
  const pts = [...points].sort((a, b) => a[0] - b[0]);
  if (x <= pts[0][0]) return pts[0][1];
  if (x >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[i + 1];
    if (x >= x0 && x <= x1) {
      const t = x1 !== x0 ? (x - x0) / (x1 - x0) : 0;
      return y0 + t * (y1 - y0);
    }
  }
  return pts[pts.length - 1][1];
}

function varEffect(v: SensVariable, stress: number, baseIrr: number): number {
  return interp(v.points, stress) - baseIrr;
}

/* ═══════════════════════════════════════════
   Display helpers
   ═══════════════════════════════════════════ */

function renderValue(v: SensVariable, stress: number): string {
  const d = v.display;
  if (d.type === 'actual') {
    const actual = d.baseValue * (1 + stress / 100);
    return `${d.prefix}${actual.toFixed(d.decimals)}${d.suffix}`;
  }
  return `${stress > 0 ? '+' : ''}${stress.toFixed(0)}%`;
}

function fmtIrr(v: number, dec = 2): string {
  return v.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
}

/* ═══════════════════════════════════════════
   Build model from parsed JSON
   ═══════════════════════════════════════════ */

function findAssumption(assumptions: any[], keywords: string[], prefer?: string): number | null {
  const lower = (s: string) => (s || '').toLowerCase();
  const matches = assumptions.filter((a: any) =>
    keywords.some(kw => lower(a.name).includes(kw))
  );
  if (matches.length === 0) return null;
  if (prefer) {
    const pref = matches.find((a: any) => lower(a.name).includes(prefer));
    if (pref) return parseFloat(pref.value);
  }
  return parseFloat(matches[0].value);
}

function guessDisplayMeta(sensLabel: string, assumptions: any[]): DisplayMeta {
  const nml = sensLabel.toLowerCase();

  if (nml.includes('wacc')) {
    const v = findAssumption(assumptions, ['wacc']);
    if (v != null && !isNaN(v)) {
      const bv = Math.abs(v) <= 1 ? v * 100 : v;
      return { type: 'actual', baseValue: bv, prefix: '', suffix: '%', decimals: 1 };
    }
  }
  if (nml.includes('utilisation')) {
    const v = findAssumption(assumptions, ['utilisation'], 'steady');
    if (v != null && !isNaN(v)) {
      const bv = Math.abs(v) <= 1 ? v * 100 : v;
      return { type: 'actual', baseValue: bv, prefix: '', suffix: '%', decimals: 0 };
    }
  }
  if (nml.includes('debt ratio')) {
    const v = findAssumption(assumptions, ['debt ratio']);
    if (v != null && !isNaN(v)) {
      const bv = Math.abs(v) <= 1 ? v * 100 : v;
      return { type: 'actual', baseValue: bv, prefix: '', suffix: '%', decimals: 0 };
    }
  }
  if (nml.includes('opex inflation')) {
    const v = findAssumption(assumptions, ['opex inflation']);
    if (v != null && !isNaN(v)) {
      const bv = Math.abs(v) <= 1 ? v * 100 : v;
      return { type: 'actual', baseValue: bv, prefix: '', suffix: '%', decimals: 1 };
    }
  }
  if (nml.includes('carbon tax') || nml.includes('carbon credit')) {
    const v = findAssumption(assumptions, ['carbon tax', 'carbon credit']);
    if (v != null && !isNaN(v)) return { type: 'actual', baseValue: v, prefix: '$', suffix: '', decimals: 0 };
  }
  if (nml.includes('throughput fee')) {
    const v = findAssumption(assumptions, ['regasification fee', 'throughput fee']);
    if (v != null && !isNaN(v)) return { type: 'actual', baseValue: v, prefix: '$', suffix: '', decimals: 2 };
  }
  if (nml.includes('demand growth') || nml.includes('gas demand')) {
    const v = findAssumption(assumptions, ['revenue growth', 'gas demand']);
    if (v != null && !isNaN(v)) {
      const bv = Math.abs(v) <= 1 ? v * 100 : v;
      return { type: 'actual', baseValue: bv, prefix: '', suffix: '%', decimals: 1 };
    }
  }
  if (nml.includes('capex overrun') || nml.includes('capex contingency')) {
    const v = findAssumption(assumptions, ['capex contingency', 'capex overrun']);
    if (v != null && !isNaN(v)) {
      const bv = Math.abs(v) <= 1 ? v * 100 : v;
      return { type: 'actual', baseValue: bv, prefix: '', suffix: '%', decimals: 0 };
    }
  }
  return { type: 'stress', baseValue: 0, prefix: '', suffix: '%', decimals: 0 };
}

function buildSensModel(parsedJson: any, scenarioKey: string): SensModel | null {
  const sensitivity = parsedJson?.sensitivity || {};
  const oneWay: any[] = sensitivity.one_way || [];
  const assumptions: any[] = parsedJson?.assumptions || [];
  const returns = parsedJson?.returns || {};
  const metrics: any[] = returns.metrics || [];
  const twoWay = sensitivity.two_way || {};

  if (oneWay.length === 0) return null;

  let baseIrr = 0.123, baseNpv = 145, basePayback = 9.2, baseDscr = 1.45, baseEquityX = 2.4;
  for (const m of metrics) {
    const val = m[scenarioKey] ?? m.base_case;
    if (val == null) continue;
    const fval = parseFloat(String(val));
    if (isNaN(fval)) continue;
    switch (m.metric) {
      case 'Project IRR (unlevered)': baseIrr = fval; break;
      case 'NPV @ WACC (USD M)': baseNpv = fval; break;
      case 'Payback period (years)': basePayback = fval; break;
      case 'DSCR — average': baseDscr = fval; break;
      case 'Equity multiple (MoM)': baseEquityX = fval; break;
    }
  }

  const variables: SensVariable[] = [];
  for (const item of oneWay) {
    const name: string = item.assumption;
    const points: [number, number][] = [
      [-20, parseFloat(item.stress_minus_20 ?? baseIrr)],
      [-10, parseFloat(item.stress_minus_10 ?? baseIrr)],
      [0, parseFloat(item.base_case ?? baseIrr)],
      [10, parseFloat(item.upside_plus_10 ?? baseIrr)],
      [20, parseFloat(item.upside_plus_20 ?? baseIrr)],
    ];

    const display = guessDisplayMeta(name, assumptions);
    let category: 'revenue' | 'cost' | 'neutral' = 'neutral';
    if (REVENUE_LABELS.has(name)) category = 'revenue';
    else if (COST_LABELS.has(name)) category = 'cost';

    variables.push({ id: slug(name), name, points, display, category });
  }

  return { baseIrr, baseNpv, basePayback, baseDscr, baseEquityX, variables, twoWay };
}

/* ═══════════════════════════════════════════
   SVG Tornado Chart (matches Python script)
   ═══════════════════════════════════════════ */

function TornadoChart({ rows, currentIrr }: { rows: TornadoRow[]; currentIrr: number }) {
  const W = 720, H = Math.max(240, rows.length * 52 + 40);
  /* Reserve 130px on the right for the two percentage readings so bars never overlap */
  const m = { t: 18, r: 130, b: 22, l: 185 };
  const plotX0 = m.l, plotX1 = W - m.r;
  const plotY0 = m.t, plotY1 = H - m.b;
  const n = rows.length;
  const rowH = n > 0 ? (plotY1 - plotY0) / n : 40;
  const center = (plotX0 + plotX1) / 2;

  const maxAbs = Math.max(...rows.map(r => Math.max(Math.abs(r.low - currentIrr), Math.abs(r.high - currentIrr))), 0.5);
  const scale = (plotX1 - plotX0) / 2 / maxAbs;

  const ticks: number[] = [];
  for (let t = -maxAbs; t <= maxAbs + 0.001; t += maxAbs / 4) ticks.push(t);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" className="overflow-visible">
      {/* Grid lines */}
      {ticks.map((tv, i) => {
        const x = center + tv * scale;
        return <line key={i} x1={x} y1={plotY0} x2={x} y2={plotY1} stroke="rgba(255,255,255,0.06)" strokeWidth="1" />;
      })}
      {/* Center baseline */}
      <line x1={center} y1={plotY0} x2={center} y2={plotY1} stroke="rgba(255,255,255,0.2)" strokeWidth="1.2" />

      {rows.map((r, i) => {
        const y = plotY0 + i * rowH + rowH / 2;
        const bh = Math.min(22, rowH * 0.56);

        /* Position each endpoint relative to center (currentIrr) */
        const xLow = center + (r.low - currentIrr) * scale;
        const xHigh = center + (r.high - currentIrr) * scale;

        /* Draw two independent bars from center to each endpoint.
           Color by POSITION: left of center = red (downside), right = green (upside).
           This automatically handles revenue vs cost variables correctly. */
        const lowOnLeft = xLow <= center;
        const highOnLeft = xHigh <= center;

        /* Readings in the reserved right margin */
        const readingX0 = plotX1 + 10;
        const readingX1 = plotX1 + 72;
        const lowerVal = Math.min(r.low, r.high);
        const higherVal = Math.max(r.low, r.high);

        return (
          <g key={i}>
            <text x={plotX0 - 12} y={y + 5} textAnchor="end" fill="#94a3b8" fontSize="13" fontFamily="inherit">
              {r.name}
            </text>
            {/* Bar for stress -20% endpoint */}
            <rect
              x={lowOnLeft ? xLow : center}
              y={y - bh / 2}
              width={Math.max(Math.abs(xLow - center), 0)}
              height={bh} rx="3"
              fill={lowOnLeft ? '#f87171' : '#4ade80'}
              opacity="0.85"
            />
            {/* Bar for stress +20% endpoint */}
            <rect
              x={highOnLeft ? xHigh : center}
              y={y - bh / 2}
              width={Math.max(Math.abs(xHigh - center), 0)}
              height={bh} rx="3"
              fill={highOnLeft ? '#f87171' : '#4ade80'}
              opacity="0.85"
            />
            {/* Readings: lower IRR in red, higher IRR in green */}
            <text x={readingX0} y={y + 4} textAnchor="start" fill="#f87171" fontSize="12" fontFamily="monospace">
              {fmtIrr(lowerVal)}%
            </text>
            <text x={readingX1} y={y + 4} textAnchor="start" fill="#4ade80" fontSize="12" fontFamily="monospace">
              {fmtIrr(higherVal)}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ═══════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════ */

export default function SensitivityPage() {
  const [modelId, setModelId] = useState('');
  const [model, setModel] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const { scenario } = useScenario();

  /* Slider state: variable id → stress value (-20 to +20) */
  const [sliderState, setSliderState] = useState<Record<string, number>>({});

  /* Build sensitivity model from loaded model */
  const sensModel = useMemo(() => {
    if (!model) return null;
    return buildSensModel(model.parsed_json, scenario);
  }, [model, scenario]);

  /* Init sliders when model / scenario changes */
  useEffect(() => {
    if (sensModel) {
      const init: Record<string, number> = {};
      for (const v of sensModel.variables) init[v.id] = 0;
      setSliderState(init);
    }
  }, [sensModel]);

  /* Load model */
  const loadModel = useCallback(async (id: string) => {
    try {
      const m = await getModel(id);
      setModel(m);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  useEffect(() => {
    const id = localStorage.getItem('investiq_model_id');
    if (!id) { setLoading(false); return; }
    setModelId(id);
    loadModel(id);
  }, [loadModel]);

  /* Re-fetch on model change */
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        const id = localStorage.getItem('investiq_model_id');
        if (id && id !== modelId) { setModelId(id); setLoading(true); loadModel(id); }
      }
    };
    const handleFocus = () => {
      const id = localStorage.getItem('investiq_model_id');
      if (id && id !== modelId) { setModelId(id); setLoading(true); loadModel(id); }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'investiq_model_id' && e.newValue && e.newValue !== modelId) {
        setModelId(e.newValue); setLoading(true); loadModel(e.newValue);
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
  }, [modelId, loadModel]);

  /* ═══════════════════════════════════════════
     Client-side computation (reactive to sliders)
     ═══════════════════════════════════════════ */

  const computed = useMemo(() => {
    if (!sensModel) return null;
    const { baseIrr, baseNpv, basePayback, baseDscr, baseEquityX, variables, twoWay } = sensModel;

    /* Additive IRR delta (same approach as Python script) */
    let totalIrrDelta = 0;
    const perVarDelta: Record<string, number> = {};
    for (const v of variables) {
      const stress = sliderState[v.id] ?? 0;
      const effect = varEffect(v, stress, baseIrr);
      totalIrrDelta += effect;
      perVarDelta[v.id] = effect;
    }
    const currentIrr = baseIrr + totalIrrDelta;

    /* NPV scales proportionally with IRR delta */
    const npvSensitivity = baseIrr !== 0 ? baseNpv / (baseIrr * 100) : 12;
    const currentNpv = baseNpv + totalIrrDelta * 100 * npvSensitivity;

    /* Payback inversely related */
    const irrRatio = baseIrr !== 0 ? currentIrr / baseIrr : 1;
    const currentPayback = irrRatio > 0 ? basePayback / irrRatio : basePayback;

    /* DSCR: revenue assumptions raise it, cost assumptions lower it */
    let dscrDelta = 0;
    for (const v of variables) {
      const stress = sliderState[v.id] ?? 0;
      const pctChange = stress / 100;
      if (v.category === 'revenue') dscrDelta += baseDscr * pctChange * 0.4;
      else if (v.category === 'cost') dscrDelta -= baseDscr * pctChange * 0.2;
    }
    const currentDscr = baseDscr + dscrDelta;

    /* Equity multiple scales with IRR ratio */
    const currentEquityX = irrRatio > 0 ? baseEquityX * irrRatio : baseEquityX;

    /* Tornado: for each variable, compute ±20% impact from current state
       (same logic as Python script: remove current variable's effect,
        add its ±20% effect, keep other slider effects) */
    const tornado: TornadoRow[] = variables.map(v => {
      const otherDelta = totalIrrDelta - (perVarDelta[v.id] || 0);
      const low = (interp(v.points, -20) + otherDelta) * 100;
      const high = (interp(v.points, 20) + otherDelta) * 100;
      return {
        name: v.name,
        low,
        high,
        impact: Math.abs(high - low),
      };
    }).sort((a, b) => b.impact - a.impact);

    /* Two-way table — shift all values by combined IRR delta */
    let twoWayShifted = twoWay;
    if (twoWay?.data) {
      const shiftedData = twoWay.data.map((row: any) => ({
        wacc: row.wacc,
        values: (row.values || []).map((v: any) =>
          v != null ? parseFloat(v) + totalIrrDelta : null
        ),
      }));
      twoWayShifted = { ...twoWay, data: shiftedData };
    }

    return {
      currentIrr: currentIrr * 100,
      currentNpv: Math.round(currentNpv),
      currentPayback: Math.round(currentPayback * 10) / 10,
      currentDscr: Math.round(currentDscr * 100) / 100,
      currentEquityX: Math.round(currentEquityX * 100) / 100,
      baseIrr: baseIrr * 100,
      baseNpv: Math.round(baseNpv),
      basePayback: Math.round(basePayback * 10) / 10,
      baseDscr: Math.round(baseDscr * 100) / 100,
      baseEquityX: Math.round(baseEquityX * 100) / 100,
      tornado,
      twoWay: twoWayShifted,
    };
  }, [sensModel, sliderState]);

  /* Handlers */
  const handleSlider = (id: string, value: number) => {
    setSliderState(prev => ({ ...prev, [id]: value }));
  };

  const resetSliders = () => {
    if (!sensModel) return;
    const init: Record<string, number> = {};
    for (const v of sensModel.variables) init[v.id] = 0;
    setSliderState(init);
  };

  const isChanged = Object.values(sliderState).some(v => v !== 0);

  /* ═══════════════════════════════════════════
     Derived display values
     ═══════════════════════════════════════════ */

  const parsed = model?.parsed_json || {};
  const assumptions: any[] = parsed.assumptions || [];

  const sidebarAssumptions = useMemo(() => {
    return assumptions.map((a: any) => {
      const v = a.value;
      const n = typeof v === 'number' ? v : parseFloat(v);
      let formatted: string;
      if (isNaN(n)) formatted = String(v);
      else if (a.unit === '%' || (n > 0 && n < 1)) formatted = `${(n * 100).toFixed(1)}%`;
      else if (a.unit === '$/MMBtu' || a.unit === '$') formatted = `$${n}`;
      else formatted = String(n);
      return { label: a.name, value: formatted };
    }).slice(0, 12);
  }, [assumptions]);

  const deltaStr = (cur: number | null | undefined, base: number | null | undefined): string => {
    if (cur == null || base == null) return '+0';
    const d = cur - base;
    if (Math.abs(d) < 0.05) return '+0';
    return `${d >= 0 ? '+' : ''}${d.toFixed(1)}`;
  };

  /* ═══════════════════════════════════════════
     Loading / empty states
     ═══════════════════════════════════════════ */

  if (loading) return <div className="flex items-center justify-center h-64 text-d-muted">Loading model...</div>;
  if (!model) return (
    <div className="text-center py-12">
      <p className="text-slate-300 mb-2">No model loaded. Upload a model first.</p>
      <Link href="/" className="text-gold-400 hover:underline">Go to Upload</Link>
    </div>
  );

  const cover = model.parsed_json?.cover ?? {};
  const c = computed;
  const vars = sensModel?.variables ?? [];

  /* ═══════════════════════════════════════════
     Render
     ═══════════════════════════════════════════ */

  return (
    <div className="flex gap-4">
      {/* ── Left Sidebar ── */}
      <div className="w-56 flex-shrink-0 space-y-4">
        {/* Decision Confidence */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
          <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">Decision Confidence</div>
          <div className="flex items-center gap-2">
            <div className="text-3xl font-bold text-white">
              {c ? `${fmtIrr(c.currentIrr, 1)}%` : '—'}
            </div>
            <span className={`w-2.5 h-2.5 rounded-full ${c && c.currentIrr >= 10 ? 'bg-green-500' : 'bg-red-500'}`} />
          </div>
          <div className={`text-xs mt-1 ${c && c.currentIrr >= 10 ? 'text-green-400' : 'text-red-400'}`}>
            {c && c.currentIrr >= 10 ? '▲ Above hurdle — Investable' : '▼ Below hurdle — Caution'}
          </div>
          <div className="mt-3 space-y-1">
            <div className="flex items-center gap-2 text-xs">
              <span className={`w-2 h-2 rounded-full ${c && c.currentIrr >= 10 ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-slate-300">IRR vs hurdle</span>
              <span className="ml-auto font-semibold">{c ? `${fmtIrr(c.currentIrr, 1)}%` : '—'}</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className={`w-2 h-2 rounded-full ${c && c.currentDscr >= 1.2 ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-slate-300">DSCR covenant</span>
              <span className="ml-auto font-semibold">{c ? `${c.currentDscr}x` : '—'}</span>
            </div>
          </div>
        </div>

        {/* Live Model KPIs */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
          <div className="text-[10px] text-d-muted uppercase tracking-wider font-medium mb-2">Live Model KPIs</div>
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">IRR</div>
              <div className="text-lg font-bold text-gold-400">{c ? `${fmtIrr(c.currentIrr, 1)}%` : '—'}</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">NPV</div>
              <div className="text-lg font-bold text-gold-400">{c ? `$${c.currentNpv}M` : '—'}</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">PAYBACK</div>
              <div className="text-lg font-bold text-white">{c ? `${c.currentPayback}yr` : '—'}</div>
            </div>
            <div className="bg-d-bg rounded p-2">
              <div className="text-[10px] text-d-muted">DSCR</div>
              <div className="text-lg font-bold text-white">{c ? `${c.currentDscr}x` : '—'}</div>
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

        {/* ── Header bar ── */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">Sensitivity Analysis</h1>
            <p className="text-sm text-d-muted">
              {cover.Project || model.original_filename}
              {c ? ` · Base IRR ${fmtIrr(c.baseIrr, 1)}% · Current scenario IRR ${fmtIrr(c.currentIrr, 2)}%` : ''}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {isChanged && (
              <button onClick={resetSliders} className="text-xs text-d-muted hover:text-white border border-d-border px-3 py-1 rounded">
                Reset to Base
              </button>
            )}
            <span className={`text-xs px-2 py-1 rounded font-medium ${isChanged ? 'bg-amber-900/30 text-amber-400' : 'bg-green-900/30 text-green-400'}`}>
              {isChanged ? 'Scenario Modified' : 'Base Case'}
            </span>
          </div>
        </div>

        {/* ── KPI Cards Row ── */}
        <div className="grid grid-cols-5 gap-3">
          {c && [
            { label: 'IRR', value: `${fmtIrr(c.currentIrr, 1)}%`, base: c.baseIrr, cur: c.currentIrr, color: 'text-gold-400' },
            { label: 'NPV', value: `$${c.currentNpv}M`, base: c.baseNpv, cur: c.currentNpv, color: 'text-gold-400' },
            { label: 'Payback', value: `${c.currentPayback} yrs`, base: c.basePayback, cur: c.currentPayback, color: 'text-gold-400' },
            { label: 'DSCR', value: `${c.currentDscr}x`, base: c.baseDscr, cur: c.currentDscr, color: 'text-gold-400' },
            { label: 'Equity ×', value: `${c.currentEquityX}x`, base: c.baseEquityX, cur: c.currentEquityX, color: 'text-gold-400' },
          ].map((kpi) => {
            const d = deltaStr(kpi.cur, kpi.base);
            return (
              <div key={kpi.label} className="bg-d-card rounded-lg shadow-sm border border-d-border p-4">
                <div className="text-xs text-d-muted uppercase tracking-wide font-medium">{kpi.label}</div>
                <div className={`text-2xl font-bold mt-1 ${kpi.color}`}>{kpi.value}</div>
                <div className="text-xs text-d-muted mt-1">
                  vs base: <span className={d.startsWith('+') && d !== '+0' ? 'text-green-400' : d.startsWith('-') ? 'text-red-400' : 'text-d-muted'}>{d}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── 2×2 Grid ── */}
        <div className="grid grid-cols-2 gap-4">

          {/* ── TOP LEFT: Assumption Sliders (stress-based, matching Python script) ── */}
          <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-white">Assumption sliders</h2>
                <p className="text-xs text-d-muted">Drag to simulate — the tornado chart updates live</p>
              </div>
            </div>
            <div className="space-y-4">
              {vars.map((v) => {
                const stress = sliderState[v.id] ?? 0;
                const changed = stress !== 0;
                return (
                  <div key={v.id}>
                    <div className="flex items-center gap-3">
                      <div className="w-44 shrink-0">
                        <div className="text-sm font-semibold text-slate-200 truncate" title={v.name}>{v.name}</div>
                        <div className="text-[10px] text-d-muted mt-0.5">
                          Current stress: <span className={changed ? 'text-gold-400' : ''}>{stress > 0 ? '+' : ''}{stress}%</span>
                        </div>
                      </div>
                      <input
                        type="range"
                        min={-20}
                        max={20}
                        step={1}
                        value={stress}
                        onChange={e => handleSlider(v.id, parseInt(e.target.value))}
                        className="flex-1 h-1.5 accent-gold-500 cursor-pointer"
                      />
                      <div className={`w-20 text-center text-xs font-mono font-bold rounded-lg px-2 py-1.5 ${
                        changed ? 'bg-gold-500 text-white' : 'bg-d-bg text-white border border-d-border'
                      }`}>
                        {renderValue(v, stress)}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── TOP RIGHT: IRR Tornado Chart (SVG, matching Python script) ── */}
          <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-sm font-semibold text-white">IRR tornado chart</h2>
              <div className="text-[10px] text-d-muted bg-d-bg px-2 py-0.5 rounded border border-d-border">±20% stress</div>
            </div>
            <p className="text-[10px] text-d-muted mb-3 uppercase tracking-wider font-medium">Ranked by impact</p>
            {c && c.tornado.length > 0 ? (
              <>
                <TornadoChart rows={c.tornado} currentIrr={c.currentIrr} />
                <div className="flex gap-4 mt-3 text-[11px] text-d-muted">
                  <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: '#f87171' }} /> downside</span>
                  <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: '#4ade80' }} /> upside</span>
                </div>
                <div className="text-[10px] text-d-muted mt-2">
                  Method: piecewise-linear interpolation on five one-way sensitivity points; project IRR approximated additively from all slider selections.
                </div>
              </>
            ) : (
              <div className="text-center py-8 text-d-muted text-xs">No sensitivity data available.</div>
            )}
          </div>

          {/* ── BOTTOM LEFT: Scenario Comparison ── */}
          <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-white">Scenario comparison</h2>
              <span className="text-[10px] text-d-muted">base vs current</span>
            </div>
            {c ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-d-muted uppercase tracking-wider">
                    <th className="text-left pb-2 font-medium">Metric</th>
                    <th className="text-right pb-2 font-medium">Base</th>
                    <th className="text-right pb-2 font-medium">Scenario</th>
                    <th className="text-right pb-2 font-medium">Δ</th>
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {[
                    { metric: 'IRR', base: c.baseIrr, cur: c.currentIrr, suffix: '%' },
                    { metric: 'NPV ($M)', base: c.baseNpv, cur: c.currentNpv, prefix: '$' },
                    { metric: 'Payback (yr)', base: c.basePayback, cur: c.currentPayback },
                    { metric: 'DSCR (avg)', base: c.baseDscr, cur: c.currentDscr, suffix: 'x' },
                    { metric: 'Equity ×', base: c.baseEquityX, cur: c.currentEquityX, suffix: 'x' },
                  ].map((row) => {
                    const d = row.cur - row.base;
                    const dStr = Math.abs(d) < 0.05 ? '+0' : `${d >= 0 ? '+' : ''}${d.toFixed(1)}`;
                    return (
                      <tr key={row.metric} className="border-b border-d-border">
                        <td className="py-2.5 font-medium text-white">{row.metric}</td>
                        <td className="py-2.5 text-right text-d-muted">{fmtTableVal(row.base, row.prefix, row.suffix)}</td>
                        <td className="py-2.5 text-right font-semibold text-white">{fmtTableVal(row.cur, row.prefix, row.suffix)}</td>
                        <td className={`py-2.5 text-right font-medium ${d > 0.05 ? 'text-green-400' : d < -0.05 ? 'text-red-400' : 'text-d-muted'}`}>{dStr}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-8 text-d-muted text-xs">No data available.</div>
            )}
          </div>

          {/* ── BOTTOM RIGHT: Two-Way Table ── */}
          <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5 overflow-x-auto">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-white">WACC × Throughput two-way table</h2>
              <span className="text-[10px] text-d-muted bg-d-bg px-2 py-0.5 rounded">IRR %</span>
            </div>
            {c?.twoWay?.data && c.twoWay.data.length > 0 ? (
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    <th className="p-1.5 text-left text-d-muted font-medium border-b">WACC / Fee</th>
                    {(c.twoWay.columns && c.twoWay.columns.length > 0
                      ? c.twoWay.columns
                      : c.twoWay.data[0]?.values?.map((_: any, i: number) => `Col ${i + 1}`)
                    ).map((col: any, i: number) => (
                      <th key={i} className="p-1.5 text-right text-d-muted font-medium border-b">{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {c.twoWay.data.map((row: any, i: number) => (
                    <tr key={i} className="border-b border-d-border">
                      <td className="p-1.5 font-medium text-slate-300">{row.wacc}</td>
                      {(row.values || []).map((v: any, j: number) => {
                        const val = typeof v === 'number' ? v : parseFloat(v);
                        const pctVal = Math.abs(val) < 1 ? val * 100 : val;
                        const baseIrrPct = c?.currentIrr ?? 12.3;
                        const isBase = Math.abs(pctVal - baseIrrPct) < 0.15;
                        return (
                          <td key={j} className={`p-1.5 text-right font-mono ${
                            isBase ? 'ring-2 ring-gold-500 ring-inset font-bold bg-d-hover' :
                            pctVal >= 10 ? 'text-green-400' : pctVal < 0 ? 'text-red-400' : 'text-amber-400'
                          }`}>
                            {isNaN(pctVal) ? '—' : `${pctVal.toFixed(1)}%`}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-8 text-d-muted text-xs">
                Two-way sensitivity data not available in model.
              </div>
            )}
          </div>
        </div>

        {/* ── Current Assumptions (reflects slider positions) ── */}
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
          <h2 className="text-sm font-semibold text-white mb-3">Current Assumptions</h2>
          <div className="grid grid-cols-4 gap-x-8 gap-y-1 text-xs">
            {vars.map((v) => {
              const stress = sliderState[v.id] ?? 0;
              const changed = stress !== 0;
              return (
                <div key={v.id} className="flex justify-between py-1 border-b border-d-border">
                  <span className="text-d-muted">{v.name}</span>
                  <span className={`font-mono font-semibold ${changed ? 'text-gold-400' : 'text-white'}`}>
                    {renderValue(v, stress)}
                    {changed && <span className="text-d-muted ml-1 text-[10px]">({stress > 0 ? '+' : ''}{stress}%)</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <FloatingAssistant tabKey="sensitivity" pageContext="Sensitivity analysis with interactive tornado chart, two-way heat map, and real-time scenario sliders" />
    </div>
  );
}

/* ── Formatting helpers ── */
function fmtTableVal(v: any, prefix?: string, suffix?: string): string {
  if (v == null || v === '' || (typeof v === 'number' && isNaN(v))) return '—';
  const num = typeof v === 'string' ? parseFloat(v) : v;
  if (isNaN(num)) return String(v);
  const formatted = Number.isInteger(num) ? String(num) : num.toFixed(1);
  return `${prefix || ''}${formatted}${suffix || ''}`;
}
