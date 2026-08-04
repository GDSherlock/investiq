'use client';

import type { KeyboardEvent } from 'react';

import type { PersonaDef } from '@/app/PersonaContext';
import type { ReportPersonaId } from '@/lib/calculation-api-types';

import { PersonaReportStarters } from './PersonaReportStarters';
import { ReportPersonaSelector } from './ReportPersonaSelector';


interface ReportChatComposerProps {
  value: string;
  disabled: boolean;
  busy?: boolean;
  persona: PersonaDef;
  personas: PersonaDef[];
  onChange: (value: string) => void;
  onPersonaChange: (id: ReportPersonaId) => void;
  onSubmit: () => void;
  onSend: (text: string) => void;
}


export function ReportChatComposer({
  value,
  disabled,
  busy = false,
  persona,
  personas,
  onChange,
  onPersonaChange,
  onSubmit,
  onSend,
}: ReportChatComposerProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!disabled && value.trim()) {
        onSubmit();
      }
    }
  };

  return (
    <div className="space-y-3 border-t border-d-border bg-d-card/95 px-4 py-4 sm:px-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <span className="shrink-0 text-xs font-semibold uppercase tracking-wider text-d-muted">
          Report persona
        </span>
        <ReportPersonaSelector
          personaId={persona.id}
          personas={personas}
          disabled={busy}
          onChange={onPersonaChange}
        />
      </div>

      <PersonaReportStarters
        prompts={[persona.starter_prompts.reports]}
        disabled={disabled}
        onSend={onSend}
      />

      <div className="flex items-end gap-3 rounded-xl border border-d-border bg-d-bg p-2 focus-within:border-gold-500/70 focus-within:ring-2 focus-within:ring-gold-500/10">
        <textarea
          data-testid="report-chat-input"
          rows={2}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? 'A ready calculation is required to send a message.'
              : 'Ask for a report, request a revision, or add a fact…'
          }
          className="max-h-36 min-h-14 flex-1 resize-y bg-transparent px-2 py-2 text-sm text-white outline-none placeholder:text-slate-500 disabled:cursor-not-allowed"
        />
        <button
          type="button"
          disabled={disabled || !value.trim()}
          onClick={onSubmit}
          className="rounded-lg bg-gold-500 px-4 py-2.5 text-sm font-semibold text-navy-950 transition hover:bg-gold-400 disabled:cursor-not-allowed disabled:bg-slate-600 disabled:text-slate-300"
        >
          {busy ? 'Generating…' : 'Send'}
        </button>
      </div>
      <p className="text-[11px] text-d-muted">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  );
}
