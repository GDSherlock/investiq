'use client';

import { useEffect, useMemo, useRef } from 'react';

import type { MonteCarloEligibleInput } from '@/lib/calculation-api-types';

interface MonteCarloCorrelationDialogProps {
  open: boolean;
  allInputs: MonteCarloEligibleInput[];
  selectedInputs: MonteCarloEligibleInput[];
  correlations: number[][];
  onCorrelationChange: (
    row: number,
    column: number,
    value: string,
  ) => void;
  onResetIdentity: () => void;
  onClose: () => void;
}

export function MonteCarloCorrelationDialog({
  open,
  allInputs,
  selectedInputs,
  correlations,
  onCorrelationChange,
  onResetIdentity,
  onClose,
}: MonteCarloCorrelationDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputIndexById = useMemo(
    () =>
      new Map(
        allInputs.map((input, index) => [input.parameter_id, index]),
      ),
    [allInputs],
  );

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || dialog === null || dialog.open) {
      return;
    }
    dialog.showModal();
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="correlation-matrix-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          onClose();
        }
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      className="m-auto w-[min(72rem,calc(100vw-2rem))] max-w-none rounded-xl border border-d-border bg-d-bg p-0 text-white shadow-2xl backdrop:bg-slate-950/80"
    >
      <section className="flex max-h-[min(70vh,44rem)] min-h-0 flex-col">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-d-border bg-d-card px-5 py-4">
          <div>
            <h2
              id="correlation-matrix-title"
              className="text-base font-semibold text-white"
            >
              Correlation matrix
            </h2>
            <p className="mt-1 text-[10px] text-d-muted">
              {selectedInputs.length} selected stochastic inputs · symmetric
              positive-definite matrix required
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onResetIdentity}
              className="rounded-lg border border-d-border px-3 py-2 text-xs font-semibold text-d-muted transition hover:border-gold-500/70 hover:text-white"
            >
              Reset identity
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-d-border px-3 py-2 text-xs font-semibold text-white transition hover:border-gold-500/70"
            >
              Close
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <div className="overflow-x-auto rounded-lg border border-d-border">
            <table className="min-w-max border-collapse text-[10px]">
              <thead className="sticky top-0 bg-d-card">
                <tr>
                  <th className="sticky left-0 min-w-44 border-b border-r border-d-border bg-d-card p-2 text-left font-medium text-d-muted">
                    Input
                  </th>
                  {selectedInputs.map((input) => (
                    <th
                      key={input.parameter_id}
                      className="w-28 max-w-28 border-b border-d-border p-2 font-medium text-d-muted"
                      title={input.label}
                    >
                      <span className="block truncate">{input.label}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {selectedInputs.map((rowInput) => {
                  const row = inputIndexById.get(rowInput.parameter_id);
                  if (row === undefined) {
                    return null;
                  }
                  return (
                    <tr key={rowInput.parameter_id}>
                      <th
                        className="sticky left-0 max-w-44 border-r border-t border-d-border bg-d-card p-2 text-left font-medium text-d-muted"
                        title={rowInput.label}
                      >
                        <span className="block truncate">
                          {rowInput.label}
                        </span>
                      </th>
                      {selectedInputs.map((columnInput) => {
                        const column = inputIndexById.get(
                          columnInput.parameter_id,
                        );
                        if (column === undefined) {
                          return null;
                        }
                        return (
                          <td
                            key={columnInput.parameter_id}
                            className="border-t border-d-border p-2 text-center"
                          >
                            <input
                              type="number"
                              min={-1}
                              max={1}
                              step={0.05}
                              disabled={row === column}
                              value={correlations[row]?.[column] ?? 0}
                              onChange={(event) =>
                                onCorrelationChange(
                                  row,
                                  column,
                                  event.target.value,
                                )
                              }
                              aria-label={`${rowInput.label} to ${columnInput.label} correlation`}
                              className="w-20 rounded border border-d-border bg-d-card px-2 py-1.5 text-center text-white disabled:cursor-not-allowed disabled:opacity-50"
                            />
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-d-border bg-d-card px-5 py-4">
          <p className="text-[10px] text-emerald-400">
            Matrix edits are applied directly to this Monte Carlo draft.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-gold-500 px-5 py-2 text-xs font-semibold text-white transition hover:bg-gold-600"
          >
            Apply correlations
          </button>
        </footer>
      </section>
    </dialog>
  );
}
