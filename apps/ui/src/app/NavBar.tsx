'use client';

import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { usePersona } from './PersonaContext';
import { useAuth } from './AuthContext';
import { useTheme } from './ThemeContext';
import { useActiveAnalysis } from './ActiveAnalysisContext';

/* ── Nav links with optional badges ── */
const NAV_LINKS: { href: string; label: string; badge?: string; badgeColor?: string }[] = [
  { href: '/dashboard', label: 'Overview' },
  { href: '/sensitivity', label: 'Sensitivity' },
  { href: '/cashflows', label: 'Cash Flow' },
  { href: '/montecarlo', label: 'Monte Carlo', badge: 'ENGINE', badgeColor: 'bg-gold-600' },
  { href: '/monitor', label: 'Monitor' },
  { href: '/reports', label: 'Reports', badge: 'AI', badgeColor: 'bg-gold-500' },
];

const PERSONA_COLORS: Record<string, string> = {
  IM: 'border-gold-400 text-gold-400',
  CF: 'border-gold-300 text-gold-300',
  BD: 'border-gold-500 text-gold-500',
  FA: 'border-slate-300 text-slate-300',
  PO: 'border-gold-200 text-gold-200',
};
const PERSONA_BG_ACTIVE: Record<string, string> = {
  IM: 'bg-gold-500/20 border-gold-400 text-gold-200',
  CF: 'bg-gold-500/15 border-gold-300 text-gold-200',
  BD: 'bg-gold-500/20 border-gold-500 text-gold-100',
  FA: 'bg-slate-500/20 border-slate-300 text-slate-200',
  PO: 'bg-gold-500/15 border-gold-200 text-gold-100',
};

export default function NavBar() {
  const pathname = usePathname();
  const { persona, setPersonaById, personas } = usePersona();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const activeAnalysis = useActiveAnalysis();
  const hasActiveModel = activeAnalysis.modelVersionId !== null;
  const modelLabel = activeAnalysis.modelVersionId
    ? `Model ${activeAnalysis.modelVersionId.slice(0, 8)}`
    : null;
  const runLabel =
    activeAnalysis.activeRunKind === 'override'
      ? 'Override'
      : activeAnalysis.activeRunKind === 'baseline'
        ? 'Baseline'
        : activeAnalysis.status === 'needs_calculation'
          ? 'Calculation required'
          : activeAnalysis.status === 'needs_readiness'
            ? 'Preparing'
            : 'No calculation';

  return (
    <div className="flex flex-col">
      {/* ═══════ ROW 1: Brand + Project pill ═══════ */}
      <div className="bg-d-card text-white overflow-x-auto">
        <div className="max-w-[1600px] mx-auto px-4 py-2 flex items-center gap-4">
          {/* Logo */}
          <div className="flex items-center gap-2 shrink-0">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-gold-400 to-gold-600 flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22,7 13.5,15.5 8.5,10.5 2,17" />
                <polyline points="16,7 22,7 22,13" />
              </svg>
            </div>
            <span className="text-lg font-bold tracking-tight">InvestIQ</span>
          </div>

          {/* Project info pill */}
          {hasActiveModel && modelLabel && (
            <div className="flex items-center gap-2 bg-d-bg border border-d-border rounded-full px-4 py-1.5 text-sm">
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${
                  activeAnalysis.status === 'ready'
                    ? 'bg-emerald-400'
                    : 'bg-gold-400'
                }`}
              />
              <span className="font-medium">{modelLabel}</span>
              <span className="text-slate-400">·</span>
              <span className="text-slate-200">{runLabel}</span>
            </div>
          )}

          {/* Canonical persisted run selection */}
          {hasActiveModel && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold shrink-0">
                Analysis
              </span>
              <span className="px-3 py-1 rounded-full text-[11px] font-semibold border border-emerald-500/70 bg-emerald-500/15 text-emerald-300">
                {activeAnalysis.activeRunKind?.toUpperCase() ?? 'PENDING'}
              </span>
            </div>
          )}

          {/* Spacer */}
          <div className="flex-1" />

          {/* User info + theme toggle + logout */}
          {user && (
            <div className="flex items-center gap-3 text-sm">
              <span className="text-slate-200">{user.name || user.email}</span>
              {/* Theme toggle */}
              <button
                onClick={toggleTheme}
                className="p-1.5 rounded-md hover:bg-d-hover border border-d-border text-d-muted transition-colors"
                title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {theme === 'dark' ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="5" />
                    <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                    <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                  </svg>
                )}
              </button>
              <button
                onClick={logout}
                className="px-3 py-1 text-xs bg-d-border hover:bg-d-hover border border-d-border rounded-md text-d-muted transition-colors"
              >
                Logout
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ═══════ ROW 2: Persona selector ═══════ */}
      <div className="bg-d-bg text-white border-t border-d-border overflow-x-auto">
        <div className="max-w-[1600px] mx-auto px-4 py-1.5 flex items-center gap-4">
          <span className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold shrink-0">Viewing as</span>
          <div className="flex items-center gap-2">
            {personas.map((p) => {
              const isActive = p.id === persona.id;
              const colorCls = isActive ? PERSONA_BG_ACTIVE[p.id] : PERSONA_COLORS[p.id];
              return (
                <button
                  key={p.id}
                  onClick={() => setPersonaById(p.id)}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all border ${
                    isActive
                      ? `${colorCls} border`
                      : `border-transparent text-slate-400 hover:text-slate-200 hover:bg-white/5`
                  }`}
                >
                  <span
                    className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold border ${
                      isActive
                        ? `${PERSONA_COLORS[p.id]} bg-transparent`
                        : 'border-slate-500 text-slate-400'
                    }`}
                  >
                    {p.short}
                  </span>
                  <span>{p.name}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* ═══════ ROW 3: Navigation links ═══════ */}
      <div className="bg-d-bg text-white border-t border-d-border overflow-x-auto">
        <div className="max-w-[1600px] mx-auto px-4 py-2 flex items-center gap-6">
          {NAV_LINKS.map(({ href, label, badge, badgeColor }) => {
            const isActive = pathname === href || (href !== '/' && pathname.startsWith(href));
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-1.5 text-sm transition-colors ${
                  isActive
                    ? 'text-gold-400 font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {isActive && <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-gold-400" />}
                <span>{label}</span>
                {badge && (
                  <span className={`${badgeColor} text-[9px] font-bold px-1.5 py-0.5 rounded ml-0.5 uppercase leading-none`}>
                    {badge}
                  </span>
                )}
              </Link>
            );
          })}

          {/* Spacer to push Financial Assistant to the right */}
          <div className="flex-1" />

          {/* Financial Assistant trigger */}
          <button
            onClick={() => window.dispatchEvent(new Event('toggle-financial-assistant'))}
            className="flex items-center gap-1.5 text-sm text-gold-400 hover:text-gold-300 transition-colors font-medium"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
            <span>Financial Assistant</span>
          </button>
        </div>
      </div>
    </div>
  );
}
