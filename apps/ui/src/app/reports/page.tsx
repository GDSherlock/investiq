'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { getModel, generatePersonaReport } from '@/lib/api';
import { usePersona } from '../PersonaContext';
import FloatingAssistant from '../FloatingAssistant';

export default function ReportsPage() {
  const [modelId, setModelId] = useState('');
  const [model, setModel] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const { persona } = usePersona();

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
        if (id && id !== modelId) { setModelId(id); setLoading(true); setReport(null); fetchModel(id); }
      }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'investiq_model_id' && e.newValue && e.newValue !== modelId) {
        setModelId(e.newValue); setLoading(true); setReport(null); fetchModel(e.newValue);
      }
    };
    document.addEventListener('visibilitychange', handleVis);
    window.addEventListener('storage', handleStorage);
    return () => { document.removeEventListener('visibilitychange', handleVis); window.removeEventListener('storage', handleStorage); };
  }, [modelId, fetchModel]);

  const generate = async () => {
    if (!modelId) return;
    setGenerating(true);
    setReport(null);
    try {
      const data = await generatePersonaReport(modelId, persona);
      setReport(data);
    } catch (err) {
      console.error(err);
    }
    setGenerating(false);
  };

  // Clear report when persona changes so user regenerates
  useEffect(() => {
    setReport(null);
  }, [persona.id]);

  const reportType = persona.report_system_addendum.report_type_default;

  if (loading) return <div className="flex items-center justify-center h-64 text-d-muted">Loading model...</div>;
  if (!model) return (
    <div className="text-center py-12">
      <p className="text-slate-300 mb-2">No model loaded. Upload a model first.</p>
      <Link href="/" className="text-gold-400 hover:underline">Go to Upload</Link>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg">📄</span>
              <h1 className="text-lg font-semibold text-white">Report Generator</h1>
            </div>
            <p className="text-xs text-d-muted mt-1">
              Persona-toned reports · Powered by Azure OpenAI
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="text-[10px] text-d-muted uppercase tracking-wider">Generating for</div>
              <div className="text-sm font-semibold text-white">{persona.name}</div>
              <div className="text-[10px] text-d-muted">{reportType}</div>
            </div>
            <button
              onClick={generate}
              disabled={generating}
              className="bg-gold-500 hover:bg-gold-600
                text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition disabled:opacity-50
                flex items-center gap-2 shadow-sm"
            >
              {generating ? (
                <span className="animate-pulse">Generating...</span>
              ) : (
                <>🚀 Generate {reportType}</>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Persona info card */}
      <div className="bg-gradient-to-r from-d-bg to-d-card rounded-lg border border-d-border p-4">
        <div className="grid grid-cols-3 gap-4 text-xs">
          <div>
            <div className="text-[10px] text-d-muted uppercase tracking-wider font-semibold mb-1">Tone</div>
            <div className="text-white">{persona.report_system_addendum.tone}</div>
          </div>
          <div>
            <div className="text-[10px] text-d-muted uppercase tracking-wider font-semibold mb-1">Emphasis</div>
            <div className="text-white">{persona.report_system_addendum.emphasis.join(' · ')}</div>
          </div>
          <div>
            <div className="text-[10px] text-d-muted uppercase tracking-wider font-semibold mb-1">Starter</div>
            <div className="text-d-muted italic">{persona.starter_prompts.reports}</div>
          </div>
        </div>
      </div>

      {/* Generated Report */}
      {generating && (
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-12 text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-4 border-d-border border-t-gold-500 mb-3" />
          <p className="text-sm text-d-muted">Generating {reportType} for {persona.name}...</p>
          <p className="text-xs text-d-muted mt-1">This may take 15-30 seconds</p>
        </div>
      )}

      {report && (
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border">
          <div className="flex items-center justify-between px-5 py-3 border-b bg-d-bg">
            <div className="flex items-center gap-2">
              <span className="text-green-400 text-sm">✓</span>
              <h2 className="text-sm font-semibold text-white">{report.report_type || reportType}</h2>
              <span className="text-[10px] bg-green-900/30 text-green-400 px-2 py-0.5 rounded font-medium">
                {report.status}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-d-muted">Persona: {report.persona || persona.name}</span>
              <span className="text-[10px] text-d-muted">ID: {report.report_id}</span>
            </div>
          </div>
          <div className="p-5 prose prose-sm prose-invert max-w-none overflow-auto max-h-[700px]">
            <div
              dangerouslySetInnerHTML={{
                __html: (report.content || '')
                  .replace(/^### (.*$)/gm, '<h3 class="text-base font-semibold text-white mt-4 mb-2">$1</h3>')
                  .replace(/^## (.*$)/gm, '<h2 class="text-lg font-bold text-white mt-6 mb-3 border-b border-d-border pb-1">$1</h2>')
                  .replace(/^# (.*$)/gm, '<h1 class="text-xl font-bold text-white mt-6 mb-3">$1</h1>')
                  .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                  .replace(/^\| (.+)/gm, (match: string) => {
                    const cells = match.split('|').filter(Boolean).map((c: string) => c.trim());
                    return `<tr>${cells.map((c: string) => `<td class="border border-d-border px-2 py-1 text-xs">${c}</td>`).join('')}</tr>`;
                  })
                  .replace(/^- (.*$)/gm, '<li class="text-xs text-white ml-4">$1</li>')
                  .replace(/\n/g, '<br/>')
              }}
            />
          </div>

          {/* Data Sources */}
          {report.sources && report.sources.length > 0 && (
            <div className="border-t border-d-border px-5 py-3 bg-d-bg">
              <p className="text-[10px] text-d-muted font-semibold uppercase tracking-wider mb-2">Data Sources (Vector DB)</p>
              <div className="flex flex-wrap gap-1.5">
                {report.sources.map((s: any, i: number) => (
                  <span key={i} className="inline-flex items-center gap-1 text-[10px] bg-d-hover text-gold-400 px-2 py-0.5 rounded-full border border-d-border">
                    📄 {s.source_sheet} · {s.source_file} ({Math.round(s.similarity * 100)}%)
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!report && !generating && (
        <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-16 text-center text-d-muted">
          <p className="text-sm">Select your persona above, then click Generate to create a {reportType}</p>
        </div>
      )}
      <FloatingAssistant tabKey="reports" pageContext="AI report generator with persona-specific IC papers, board memos, risk reports" />
    </div>
  );
}
