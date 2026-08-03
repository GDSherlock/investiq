'use client';

import { useMemo, useState } from 'react';

import type { HistoricalModelItem } from '@/lib/calculation-api-types';

interface HistoricalModelSelectorProps {
  models: HistoricalModelItem[];
  loading: boolean;
  error: Error | null;
  selectedModelId: string | null;
  onSelectedModelIdChange: (modelId: string) => void;
  onContinue: (model: HistoricalModelItem) => void;
  onRetry: () => void;
  onUseUpload?: () => void;
}

function displayName(model: HistoricalModelItem): string {
  return model.filename.replace(/\.xlsx$/i, '') || model.filename;
}

function modelLabel(model: HistoricalModelItem): string {
  return `${displayName(model)} — ${model.model_version_id.slice(0, 8)}`;
}

function updatedLabel(updatedAt: string): string {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) {
    return 'Updated date unavailable';
  }
  return `Updated ${new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date)}`;
}

function calculationStatusLabel(model: HistoricalModelItem): string {
  return model.calculation_status === 'baseline_ready'
    ? 'Baseline ready'
    : 'Calculation required';
}

function metadataLabel(model: HistoricalModelItem): string {
  return `${updatedLabel(model.updated_at)} · ${calculationStatusLabel(model)}`;
}

export function HistoricalModelSelector({
  models,
  loading,
  error,
  selectedModelId,
  onSelectedModelIdChange,
  onContinue,
  onRetry,
  onUseUpload,
}: HistoricalModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const selectedModel = useMemo(
    () =>
      models.find(
        (model) => model.model_version_id === selectedModelId,
      ) ?? null,
    [models, selectedModelId],
  );
  const unavailable = loading || error !== null || models.length === 0;

  return (
    <section className="mx-auto max-w-[816px] rounded-xl border border-d-border bg-d-card/35 px-5 py-7 sm:px-8 sm:py-8">
      <div className="mx-auto max-w-lg">
        <h2 className="text-xl font-semibold text-white sm:text-2xl">
          Select an existing model
        </h2>
        <p className="mt-2 text-sm text-d-muted sm:text-base">
          Continue from a prepared model and its latest calculation state.
        </p>

        <div className="mt-6">
          <label className="text-sm font-medium text-slate-200">Model</label>
          {loading ? (
            <p className="mt-2 rounded-lg border border-d-border bg-d-bg px-4 py-4 text-sm text-d-muted">
              Loading prepared models…
            </p>
          ) : error ? (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3">
              <p className="text-sm text-red-200">
                Prepared models could not be loaded.
              </p>
              <button
                type="button"
                onClick={onRetry}
                className="rounded-md border border-red-400/70 px-3 py-1.5 text-sm font-medium text-red-100 transition hover:bg-red-500/15"
              >
                Try again
              </button>
            </div>
          ) : models.length === 0 ? (
            <p className="mt-2 rounded-lg border border-d-border bg-d-bg px-4 py-4 text-sm text-d-muted">
              No prepared models are available yet.
            </p>
          ) : (
            <div className="relative mt-2">
              <button
                type="button"
                data-testid="historical-model-picker"
                aria-haspopup="listbox"
                aria-expanded={open}
                onClick={() => setOpen((current) => !current)}
                className="w-full rounded-lg border border-gold-500 bg-d-bg px-4 py-3 text-left transition hover:border-gold-400 focus:outline-none focus:ring-2 focus:ring-gold-400/40"
              >
                <span className="block text-base font-medium text-white">
                  {selectedModel
                    ? modelLabel(selectedModel)
                    : 'Select a model'}
                </span>
                {selectedModel ? (
                  <span className="mt-1 block text-sm text-d-muted">
                    {metadataLabel(selectedModel)}
                  </span>
                ) : null}
              </button>

              {open ? (
                <ul
                  role="listbox"
                  aria-label="Prepared models"
                  className="z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-slate-500 bg-navy-900 shadow-2xl shadow-black/35"
                >
                  {models.map((model) => {
                    const selected =
                      model.model_version_id === selectedModelId;
                    return (
                      <li
                        key={model.model_version_id}
                        role="option"
                        aria-selected={selected}
                        className="border-b border-d-border last:border-b-0"
                      >
                        <button
                          type="button"
                          data-model-id={model.model_version_id}
                          onClick={() => {
                            onSelectedModelIdChange(
                              model.model_version_id,
                            );
                            setOpen(false);
                          }}
                          className={`w-full px-4 py-3 text-left transition ${
                            selected
                              ? 'bg-gold-500 text-navy-950'
                              : 'bg-d-card text-white hover:bg-d-hover'
                          }`}
                        >
                          <span className="block text-base font-semibold">
                            {modelLabel(model)}
                          </span>
                          <span
                            className={`mt-1 block text-sm ${
                              selected ? 'text-navy-800' : 'text-d-muted'
                            }`}
                          >
                            {metadataLabel(model)}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </div>
          )}
        </div>

        <button
          type="button"
          data-testid="continue-with-historical-model"
          disabled={unavailable || selectedModel === null}
          onClick={() => {
            if (selectedModel) onContinue(selectedModel);
          }}
          className="mt-6 w-full rounded-lg bg-gold-500 px-5 py-3 text-base font-semibold text-navy-950 transition hover:bg-gold-400 disabled:cursor-not-allowed disabled:bg-slate-600 disabled:text-slate-300"
        >
          Continue to analysis
        </button>

        <button
          type="button"
          data-testid="use-workbook-upload"
          onClick={onUseUpload}
          className="mx-auto mt-4 block text-sm font-medium text-gold-400 underline-offset-4 transition hover:text-gold-300 hover:underline"
        >
          Upload a new workbook instead
        </button>
      </div>
    </section>
  );
}
