'use client';

import type { PersonaDef } from '@/app/PersonaContext';
import type { ReportPersonaId } from '@/lib/calculation-api-types';


interface ReportPersonaSelectorProps {
  personaId: ReportPersonaId;
  personas: PersonaDef[];
  disabled?: boolean;
  onChange: (id: ReportPersonaId) => void;
}


export function ReportPersonaSelector({
  personaId,
  personas,
  disabled = false,
  onChange,
}: ReportPersonaSelectorProps) {
  return (
    <div
      className="flex max-w-full items-center gap-1 overflow-x-auto"
      role="group"
      aria-label="Report persona"
    >
      {personas.map((persona) => {
        const selected = persona.id === personaId;
        return (
          <button
            key={persona.id}
            type="button"
            data-persona-id={persona.id}
            aria-pressed={selected}
            disabled={disabled}
            onClick={() => onChange(persona.id)}
            className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
              selected
                ? 'border-gold-400 bg-gold-500/20 text-gold-200'
                : 'border-d-border bg-d-bg text-d-muted hover:border-slate-500 hover:text-slate-200'
            }`}
          >
            <span className="mr-1.5">{persona.short}</span>
            <span>{persona.name}</span>
          </button>
        );
      })}
    </div>
  );
}
