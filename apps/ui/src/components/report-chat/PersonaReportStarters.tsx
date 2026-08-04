'use client';


interface PersonaReportStartersProps {
  prompts: string[];
  disabled: boolean;
  onSend: (text: string) => void;
}


export function PersonaReportStarters({
  prompts,
  disabled,
  onSend,
}: PersonaReportStartersProps) {
  return (
    <div className="flex flex-wrap gap-2" aria-label="Report starter prompts">
      {prompts.map((prompt) => (
        <button
          key={prompt}
          type="button"
          disabled={disabled}
          onClick={() => onSend(prompt)}
          className="rounded-full border border-d-border bg-d-bg px-3 py-1.5 text-xs text-slate-300 transition hover:border-gold-500/60 hover:text-gold-300 disabled:cursor-not-allowed disabled:opacity-45"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}
