'use client';

export type ModelSourceMode = 'upload' | 'history';

interface ModelSourceSwitcherProps {
  mode: ModelSourceMode;
  onModeChange: (mode: ModelSourceMode) => void;
}

const options: { mode: ModelSourceMode; label: string }[] = [
  { mode: 'upload', label: 'Upload new model' },
  { mode: 'history', label: 'Use existing model' },
];

export function ModelSourceSwitcher({
  mode,
  onModeChange,
}: ModelSourceSwitcherProps) {
  return (
    <div
      role="tablist"
      aria-label="Choose a model source"
      className="mx-auto grid w-full max-w-xl grid-cols-2 rounded-xl border border-d-border bg-d-card/70 p-1 shadow-lg shadow-black/10"
    >
      {options.map((option) => {
        const selected = option.mode === mode;
        return (
          <button
            key={option.mode}
            type="button"
            role="tab"
            aria-selected={selected}
            data-model-source={option.mode}
            onClick={() => onModeChange(option.mode)}
            className={`rounded-lg px-4 py-2.5 text-sm font-semibold transition sm:text-base ${
              selected
                ? 'bg-gold-500 text-navy-950 shadow-sm'
                : 'text-slate-300 hover:bg-d-hover hover:text-white'
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
