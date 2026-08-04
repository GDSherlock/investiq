'use client';

import { useState } from 'react';

const PROBLEMS = [
  { title: 'Analysis cycle time', desc: '3-5 days to rebuild a scenario' },
  { title: 'Model opacity', desc: 'Access restricted to the model author' },
  { title: 'Fragmented risk signals', desc: 'Signals spread across systems' },
  { title: 'Manual report production', desc: 'Consumes 30-40% of investment manager time' },
];

const CAPABILITIES = [
  { title: 'Model overview', desc: 'Upload Excel, auto-parse, health check, live KPIs', icon: '📊' },
  { title: 'Sensitivity engine', desc: 'Live sliders, tornado chart, sensitivity & carbon tables, AI in 3 lines', icon: '🎛️' },
  { title: 'Cash flow simulator', desc: 'P10/P50/P90, DSCR covenant, payback tracking', icon: '💰' },
  { title: 'Monte Carlo engine', desc: 'Configure distributions, 5,000 trials, hurdle probability, VaR', icon: '🎲' },
  { title: 'AI assistant', desc: 'Persona-aware chat — full model context, concise answers, sources shown', icon: '🤖' },
  { title: 'Report generator', desc: 'IC paper, board 1-pager, variance report — live data, instant', icon: '📄' },
];

const PERSONAS = [
  { role: 'Investment Manager', desc: 'Full platform access — IRR drivers, sensitivity engine, model audit', color: 'text-gold-400' },
  { role: 'CFO', desc: 'Covenant monitoring, board reporting, cash flow management, capital structure', color: 'text-blue-400' },
  { role: 'Board Director', desc: 'Plain-English verdict, strategic risk, governance triggers — no jargon', color: 'text-green-400' },
  { role: 'Financial Analyst', desc: 'Model audit, formula logic, assumption sources, data lineage', color: 'text-purple-400' },
  { role: 'Project Owner', desc: 'Milestone tracker, capex overrun, schedule risk', color: 'text-orange-400' },
];

const MODULES = [
  {
    title: 'Model overview',
    desc: 'Upload your Excel model or use the built-in LNG sample. InvestIQ auto-parses all sheets, maps assumptions, runs a health check, and shows live KPIs.',
    bullets: [
      'Upload any .xlsx DCF, project finance, or LBO model',
      '6 KPIs update live: IRR, NPV, Payback, DSCR, Equity multiple',
      'Model health check flags hardcoded cells and formula integrity gaps',
      'Revenue and EBITDA trajectory chart updates with every assumption change',
    ],
  },
  {
    title: 'Sensitivity engine + AI analysis',
    desc: 'The core daily tool. Drag any of 8 sliders — every KPI, table, and chart updates instantly. Hit "Analyse Impact" for a 3-line AI insight framed for your persona.',
    bullets: [
      '8 live sliders: WACC, throughput, utilisation, carbon, overrun + more',
      'IRR tornado chart — ranked by impact, updates per slider drag',
      'Full sensitivity table: -20% / -10% / base / +10% / +20% per variable with IRR range bar',
      'AI analysis: 3-cell Signal | Driver | Action format',
    ],
  },
  {
    title: 'Monte Carlo simulation engine',
    desc: 'Configure probability distributions for each variable. The engine runs configurable trials and reports IRR distribution, NPV histogram, and probability of beating the hurdle rate.',
    bullets: [
      'Configure mean, standard deviation, and distribution type per variable',
      'Runs 5,000 trials with progress indicator — takes ~3 seconds',
      'Reports P10/P50/P90 IRR, probability of hurdle breach, and value at risk',
      'IRR and NPV distribution histograms with hurdle rate marker',
    ],
  },
  {
    title: 'Cash flow simulator',
    desc: 'P10/P50/P90 bands, DSCR covenant year-by-year, cumulative payback tracking. AI interprets the profile for your persona in 3 lines.',
    bullets: [
      'Annual FCF bar chart — positive years green, construction negative years red',
      'P10/P50/P90 distribution bands based on current assumptions',
      'DSCR by year with 1.25x covenant line — trough year flagged',
      'AI: 3-cell "Profile | Risk period | Monitor this" format',
    ],
  },
  {
    title: 'Report generator',
    desc: 'IC papers, Board 1-pagers, and variance reports generated from live model data in 1 second. Persona-framed, tone-configurable, exportable.',
    bullets: [
      'IC paper: executive summary, investment rationale, returns, risks, recommendation',
      'Board 1-pager: plain English, no jargon, headline-first format',
      'Variance report: actuals, schedule status, risk watch items, management actions',
      'All reports use live model values — change a slider and regenerate',
    ],
  },
];

interface IntroductionPageProps {
  onSkip: () => void;
}

export default function IntroductionPage({ onSkip }: IntroductionPageProps) {
  const [page, setPage] = useState(0);
  const totalPages = 3;

  return (
    <div className="fixed inset-0 z-[100] bg-d-bg overflow-y-auto" style={{ backgroundColor: 'rgb(var(--d-bg))' }}>
      {/* Skip button */}
      <button
        onClick={onSkip}
        className="fixed top-6 right-6 z-[110] flex items-center gap-2 px-5 py-2.5 bg-d-card border border-d-border rounded-lg text-sm font-medium text-d-muted hover:text-white hover:border-gold-400 transition-all"
      >
        Skip
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>

      {/* Page indicators */}
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[110] flex items-center gap-3">
        {Array.from({ length: totalPages }).map((_, i) => (
          <button
            key={i}
            onClick={() => setPage(i)}
            className={`w-2.5 h-2.5 rounded-full transition-all ${i === page ? 'bg-gold-400 w-8' : 'bg-d-border hover:bg-d-dim'}`}
          />
        ))}
      </div>

      {/* Navigation arrows */}
      <div className="fixed bottom-6 right-6 z-[110] flex items-center gap-2">
        {page > 0 && (
          <button
            onClick={() => setPage(page - 1)}
            className="px-4 py-2 bg-d-card border border-d-border rounded-lg text-sm text-d-muted hover:text-white hover:border-gold-400 transition"
          >
            ← Prev
          </button>
        )}
        {page < totalPages - 1 ? (
          <button
            onClick={() => setPage(page + 1)}
            className="px-4 py-2 bg-gold-500 rounded-lg text-sm text-white font-medium hover:bg-gold-600 transition"
          >
            Next →
          </button>
        ) : (
          <button
            onClick={onSkip}
            className="px-5 py-2 bg-gold-500 rounded-lg text-sm text-white font-medium hover:bg-gold-600 transition"
          >
            Get Started →
          </button>
        )}
      </div>

      <div className="max-w-[1200px] mx-auto px-6 py-12 pb-24">
        {/* ── Page 1: Welcome ── */}
        {page === 0 && (
          <div className="animate-fadeIn">
            {/* Hero */}
            <div className="text-center mb-12">
              <h1 className="text-5xl font-bold text-white mb-4">Welcome to InvestIQ</h1>
              <p className="text-xl text-gold-400">AI-powered financial model intelligence for infrastructure investment teams</p>
            </div>

            <p className="text-d-muted text-center max-w-3xl mx-auto mb-10 leading-relaxed">
              InvestIQ addresses four structural problems in infrastructure investment: analysis cycle time,
              model opacity, fragmented risk signals, and manual report production.
            </p>

            {/* Problem cards */}
            <div className="grid grid-cols-4 gap-4 mb-14">
              {PROBLEMS.map((p) => (
                <div key={p.title} className="bg-d-card border border-d-border rounded-xl p-5 text-center">
                  <div className="text-sm font-semibold text-white mb-2">{p.title}</div>
                  <div className="text-xs text-d-muted">{p.desc}</div>
                </div>
              ))}
            </div>

            {/* Core capabilities */}
            <h2 className="text-2xl font-bold text-white mb-6">Core capabilities</h2>
            <div className="grid grid-cols-2 gap-4 mb-14">
              {CAPABILITIES.map((c) => (
                <div key={c.title} className="bg-d-card border border-d-border rounded-xl p-5 flex items-start gap-4">
                  <span className="text-2xl flex-shrink-0">{c.icon}</span>
                  <div>
                    <div className="text-sm font-semibold text-gold-400 mb-1">{c.title}</div>
                    <div className="text-xs text-d-muted leading-relaxed">{c.desc}</div>
                  </div>
                </div>
              ))}
            </div>

            {/* Persona system */}
            <h2 className="text-2xl font-bold text-white mb-3">Role-based persona system</h2>
            <p className="text-sm text-d-muted mb-6">
              Every AI output, chart label and report adapts to your role. Switch persona from the report composer when you need a different perspective.
            </p>
            <div className="space-y-3">
              {PERSONAS.map((p) => (
                <div key={p.role} className="bg-d-card border border-d-border rounded-xl px-5 py-3 flex items-center gap-4">
                  <span className={`text-sm font-semibold ${p.color} min-w-[160px]`}>{p.role}</span>
                  <span className="text-xs text-d-muted">{p.desc}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Page 2: Modules ── */}
        {page === 1 && (
          <div className="animate-fadeIn">
            <h1 className="text-3xl font-bold text-white mb-10">Modules in the application</h1>
            <div className="space-y-8">
              {MODULES.map((m) => (
                <div key={m.title} className="bg-d-card border border-d-border rounded-xl p-6">
                  <h3 className="text-lg font-semibold text-gold-400 mb-2">{m.title}</h3>
                  <p className="text-sm text-d-muted mb-4 leading-relaxed">{m.desc}</p>
                  <ul className="space-y-2">
                    {m.bullets.map((b, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                        <span className="w-1.5 h-1.5 rounded-full bg-gold-400 mt-1.5 flex-shrink-0" />
                        {b}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Page 3: Architecture ── */}
        {page === 2 && (
          <div className="animate-fadeIn">
            <h1 className="text-3xl font-bold text-white mb-10">Technical architecture</h1>

            <div className="bg-d-card border border-d-border rounded-xl p-8 mb-8">
              <img
                src="/architecture-diagram.png"
                alt="Technical Architecture Diagram of Investment &amp; Capital Decision Intelligence Application"
                className="w-full rounded-lg"
              />
            </div>

            {/* Diagram explanation */}
            <div className="bg-d-card border border-d-border rounded-xl p-6">
              <h3 className="text-sm font-semibold text-gold-400 mb-4">How it works</h3>
              <ul className="space-y-3">
                {[
                  'Users log into the Agent UI.',
                  'Traffic enters through Application Gateways.',
                  'The application runs in Container Apps Environments with a central Container App.',
                  'Container Registries store container images, pushed and pulled over HTTPS.',
                  'Key Vaults fetch secrets through System Assigned Managed Identity.',
                  'Application Insights collects logs, flowing into Log Analytics Workspace.',
                  'The data tier includes Storage Accounts and Azure Database PostgreSQL.',
                  'For AI capabilities, the Container App calls Azure AI Foundry.',
                  'Azure AI Foundry connects to Azure OpenAI through a model deployment call.',
                ].map((item, i) => (
                  <li key={i} className="flex items-start gap-3 text-xs text-slate-300">
                    <span className="w-1.5 h-1.5 rounded-full bg-gold-400 mt-1.5 flex-shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
