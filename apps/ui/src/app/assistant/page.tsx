'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { getModel, chatWithAssistant } from '@/lib/api';
import { usePersona } from '../PersonaContext';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: { section: string; source_sheet: string; source_file: string; similarity: number }[];
}

export default function AssistantPage() {
  const [modelId, setModelId] = useState('');
  const [model, setModel] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
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
        if (id && id !== modelId) { setModelId(id); setLoading(true); fetchModel(id); }
      }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'investiq_model_id' && e.newValue && e.newValue !== modelId) {
        setModelId(e.newValue); setLoading(true); fetchModel(e.newValue);
      }
    };
    document.addEventListener('visibilitychange', handleVis);
    window.addEventListener('storage', handleStorage);
    return () => { document.removeEventListener('visibilitychange', handleVis); window.removeEventListener('storage', handleStorage); };
  }, [modelId, fetchModel]);

  // Clear messages when persona changes
  useEffect(() => {
    setMessages([]);
  }, [persona.id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async (text?: string) => {
    const query = (text || input).trim();
    if (!query || !modelId || sending) return;

    const userMsg: ChatMessage = { role: 'user', content: query };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setSending(true);

    try {
      const data = await chatWithAssistant(modelId, query, persona, messages);
      setMessages((prev) => [...prev, { role: 'assistant', content: data.response, sources: data.sources }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Sorry, an error occurred. Please try again.' }]);
    }
    setSending(false);
  };

  const starterPrompts = [
    { key: 'assistant', label: persona.starter_prompts.assistant },
    { key: 'overview', label: persona.starter_prompts.overview },
    { key: 'sensitivity', label: persona.starter_prompts.sensitivity },
    { key: 'cash_flow', label: persona.starter_prompts.cash_flow },
    { key: 'monitor', label: persona.starter_prompts.monitor },
  ];

  if (loading) return <div className="flex items-center justify-center h-64 text-d-muted">Loading model...</div>;
  if (!model) return (
    <div className="text-center py-12">
      <p className="text-d-muted mb-2">No model loaded. Upload a model first.</p>
      <Link href="/" className="text-blue-400 hover:underline">Go to Upload</Link>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-d-card rounded-lg shadow-sm border border-d-border p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg">🤖</span>
              <h1 className="text-lg font-semibold text-white">AI Assistant</h1>
            </div>
            <p className="text-xs text-d-muted mt-1">
              Persona-toned Q&A · Powered by Azure OpenAI GPT-5.2
            </p>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-d-muted uppercase tracking-wider">Responding as</div>
            <div className="text-sm font-semibold text-white">{persona.name}</div>
            <div className="text-[10px] text-d-muted italic">{persona.assistant_system_addendum.voice}</div>
          </div>
        </div>
      </div>

      {/* Chat area */}
      <div className="bg-d-card rounded-lg shadow-sm border border-d-border flex flex-col" style={{ height: '520px' }}>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <div className="text-center pt-12">
              <p className="text-d-muted text-sm mb-4">
                Ask about the financial model as <strong>{persona.name}</strong>
              </p>
              <div className="flex flex-wrap gap-2 justify-center max-w-lg mx-auto">
                {starterPrompts.map((sp) => (
                  <button
                    key={sp.key}
                    onClick={() => send(sp.label)}
                    className="text-xs bg-d-bg hover:bg-d-hover hover:text-gold-300 text-slate-300
                      border border-d-border hover:border-d-border px-3 py-1.5 rounded-full transition"
                  >
                    {sp.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-lg px-4 py-2.5 text-sm ${
                msg.role === 'user'
                  ? 'bg-navy-700 text-white'
                  : 'bg-d-bg text-white border border-d-border'
              }`}>
                <pre className="whitespace-pre-wrap font-sans leading-relaxed">{msg.content}</pre>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-d-border">
                    <p className="text-[10px] text-d-muted font-semibold uppercase tracking-wider mb-1">Data Sources</p>
                    <div className="flex flex-wrap gap-1">
                      {msg.sources.map((s, si) => (
                        <span key={si} className="inline-flex items-center gap-1 text-[10px] bg-d-hover text-gold-400 px-2 py-0.5 rounded-full border border-d-border">
                          📄 {s.source_sheet} · {s.source_file} ({Math.round(s.similarity * 100)}%)
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {sending && (
            <div className="flex justify-start">
              <div className="bg-d-bg text-d-muted rounded-lg px-4 py-2.5 text-sm border border-d-border">
                <span className="animate-pulse">Thinking as {persona.name}...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-d-border p-3">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
              placeholder={`Ask as ${persona.name}...`}
              disabled={sending}
              className="flex-1 bg-sky-900/40 border border-d-border rounded-lg px-4 py-2 text-sm
                focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent
                disabled:bg-d-bg text-white placeholder-d-muted"
            />
            <button
              onClick={() => send()}
              disabled={!input.trim() || sending}
              className="bg-gold-500 hover:bg-gold-600 text-white px-5 py-2 rounded-lg text-sm
                font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Send
            </button>
          </div>
          <div className="text-[10px] text-d-muted mt-1.5 flex items-center gap-1">
            <span>Focus: {persona.assistant_system_addendum.primary_focus.join(' · ')}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
