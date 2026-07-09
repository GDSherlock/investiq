'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { usePersona } from './PersonaContext';
import { chatWithAssistant } from '@/lib/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface FloatingAssistantProps {
  /** Which tab the assistant is on — used for starter prompts */
  tabKey: 'overview' | 'sensitivity' | 'cash_flow' | 'monte_carlo' | 'monitor' | 'reports';
  /** Brief description of what's on screen for context */
  pageContext?: string;
}

export default function FloatingAssistant({ tabKey, pageContext }: FloatingAssistantProps) {
  const { persona } = usePersona();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Listen for toggle event from NavBar
  useEffect(() => {
    const handler = () => setOpen(prev => !prev);
    window.addEventListener('toggle-financial-assistant', handler);
    return () => window.removeEventListener('toggle-financial-assistant', handler);
  }, []);

  // Reset chat when persona changes
  useEffect(() => {
    setMessages([]);
  }, [persona.id]);

  const modelId = typeof window !== 'undefined' ? localStorage.getItem('investiq_model_id') : null;

  const starterPrompt = persona.starter_prompts[tabKey] || 'Tell me about this page.';

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || !modelId) return;
    const userMsg: Message = { role: 'user', content: text.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const contextPrefix = pageContext
        ? `[The user is viewing the ${tabKey.replace('_', ' ')} page. Page context: ${pageContext}]\n\n`
        : `[The user is viewing the ${tabKey.replace('_', ' ')} page.]\n\n`;

      const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }));
      const res = await chatWithAssistant(
        modelId,
        contextPrefix + text.trim(),
        persona.assistant_system_addendum,
        history,
      );
      const reply = res.response || res.detail || 'Sorry, no response received.';
      setMessages(prev => [...prev, { role: 'assistant', content: reply }]);
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, an error occurred.' }]);
    } finally {
      setLoading(false);
    }
  }, [modelId, messages, persona, tabKey, pageContext]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  return (
    <>
      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-6 right-6 z-50 w-96 h-[520px] bg-d-card border border-d-border rounded-2xl shadow-2xl shadow-black/40 flex flex-col overflow-hidden" style={{ backgroundColor: 'rgb(var(--d-card))' }}>
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-d-border" style={{ backgroundColor: 'rgb(var(--d-bg) / 0.9)' }}>
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-8 h-8 rounded-full bg-gold-500 flex items-center justify-center text-lg flex-shrink-0" role="img" aria-label="AI Assistant">🤖</span>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-white truncate">AI Assistant</div>
                <div className="text-[10px] text-d-muted truncate">Responding as {persona.name}</div>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setMessages([])}
                className="p-1.5 rounded hover:bg-d-hover text-d-muted hover:text-white transition"
                title="Clear chat"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" /></svg>
              </button>
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded hover:bg-d-hover text-d-muted hover:text-white transition"
                title="Close"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3" style={{ backgroundColor: 'rgb(var(--d-card))' }}>
            {messages.length === 0 && !loading && (
              <div className="text-center py-6">
                <p className="text-xs text-d-muted mb-3">Ask about the data on this page</p>
                <button
                  onClick={() => sendMessage(starterPrompt)}
                  className="text-xs bg-d-bg border border-d-border rounded-lg px-3 py-2 text-gold-400 hover:border-gold-400 hover:bg-d-hover/30 transition"
                >
                  {starterPrompt}
                </button>
              </div>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap break-words overflow-hidden ${
                    msg.role === 'user'
                      ? 'bg-gold-500/20 text-white border border-gold-500/30'
                      : 'bg-d-bg text-slate-200 border border-d-border'
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-d-bg border border-d-border rounded-xl px-3 py-2 text-xs text-d-muted">
                  <span className="inline-flex gap-1">
                    <span className="animate-bounce" style={{ animationDelay: '0ms' }}>.</span>
                    <span className="animate-bounce" style={{ animationDelay: '150ms' }}>.</span>
                    <span className="animate-bounce" style={{ animationDelay: '300ms' }}>.</span>
                  </span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <form onSubmit={handleSubmit} className="px-3 py-2 border-t border-d-border" style={{ backgroundColor: 'rgb(var(--d-bg) / 0.9)' }}>
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder={`Ask as ${persona.name}...`}
                disabled={loading || !modelId}
                className="flex-1 bg-d-bg border border-d-border rounded-lg px-3 py-2 text-xs text-white placeholder-d-muted outline-none focus:border-gold-400 transition disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={loading || !input.trim() || !modelId}
                className="bg-gold-500 hover:bg-gold-600 disabled:bg-d-dim disabled:cursor-not-allowed text-white rounded-lg px-3 py-2 text-xs font-medium transition"
              >
                Send
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
