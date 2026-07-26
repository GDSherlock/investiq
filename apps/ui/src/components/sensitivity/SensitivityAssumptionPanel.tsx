import { useMemo, useState } from 'react';

import {
  deriveSliderControlStep,
  deriveSliderSpec,
  type SensitivityAssumption,
} from '../../lib/sensitivity-analysis';

interface SensitivityAssumptionPanelProps {
  assumptions: SensitivityAssumption[];
  overridesByTarget: Record<string, string>;
  onValueChange: (targetKey: string, value: string) => void;
  onReset: (targetKey: string) => void;
  onResetAll: () => void;
}

interface NumberEditorDraft {
  targetKey: string;
  value: string;
}

const FINITE_DECIMAL_PATTERN =
  /^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$/;

function normalizeFiniteDecimalDraft(value: string): string | null {
  const trimmed = value.trim();
  if (
    !FINITE_DECIMAL_PATTERN.test(trimmed) ||
    !Number.isFinite(Number(trimmed))
  ) {
    return null;
  }
  return trimmed.replace(
    /^([+-]?)\./,
    (_match, sign: string) => `${sign}0.`,
  );
}

function displayValue(value: string, unit: string | null): string {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return 'Unavailable';
  }
  const displayedValue = unit?.trim() === '%' ? numericValue * 100 : numericValue;
  const formatted = displayedValue.toLocaleString(undefined, {
    maximumFractionDigits: 6,
  });
  return unit ? `${formatted} ${unit}` : formatted;
}

function categoryGroups(
  assumptions: SensitivityAssumption[],
): Array<{ category: string; assumptions: SensitivityAssumption[] }> {
  const groups = new Map<string, SensitivityAssumption[]>();
  for (const assumption of assumptions) {
    const category = assumption.category?.trim() || 'Other assumptions';
    const existing = groups.get(category);
    if (existing) {
      existing.push(assumption);
    } else {
      groups.set(category, [assumption]);
    }
  }
  return Array.from(groups, ([category, groupedAssumptions]) => ({
    category,
    assumptions: groupedAssumptions,
  }));
}

export function SensitivityAssumptionPanel({
  assumptions,
  overridesByTarget,
  onValueChange,
  onReset,
  onResetAll,
}: SensitivityAssumptionPanelProps) {
  const groupedAssumptions = useMemo(
    () => categoryGroups(assumptions),
    [assumptions],
  );
  const [numberEditorDraft, setNumberEditorDraft] =
    useState<NumberEditorDraft | null>(null);
  const hasOverrides = Object.keys(overridesByTarget).length > 0;

  return (
    <div className="min-w-0">
      <div className="mb-3 flex items-center justify-end">
        <button
          type="button"
          onClick={onResetAll}
          disabled={!hasOverrides}
          className="rounded border border-d-border px-2.5 py-1.5 text-xs text-slate-200 transition hover:border-gold-400 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          Reset all
        </button>
      </div>

      <div className="space-y-5">
        {assumptions.length === 0 ? (
          <p className="rounded border border-amber-800/50 bg-amber-900/10 p-3 text-sm text-amber-200">
            This model has no editable numeric canonical parameters.
          </p>
        ) : null}

        {groupedAssumptions.map((group) => (
          <section key={group.category}>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gold-300">
              {group.category}
            </h3>
            <div className="space-y-3">
              {group.assumptions.map((assumption) => {
                const value =
                  overridesByTarget[assumption.targetKey] ??
                  assumption.currentValue;
                const baseSpec = deriveSliderSpec(assumption.currentValue);
                const sliderSpec =
                  baseSpec.kind === 'number'
                    ? deriveSliderSpec(value)
                    : baseSpec;
                const sliderControlStep =
                  sliderSpec.kind === 'range'
                    ? deriveSliderControlStep(sliderSpec, value)
                    : null;
                const activeNumberDraft =
                  numberEditorDraft?.targetKey === assumption.targetKey
                    ? numberEditorDraft
                    : null;
                const showRangeInput =
                  sliderSpec.kind === 'range' &&
                  sliderControlStep !== null &&
                  activeNumberDraft === null;
                const inputId = `assumption-${assumption.targetKey}`;
                const changed =
                  overridesByTarget[assumption.targetKey] !== undefined;

                return (
                  <div
                    key={assumption.targetKey}
                    className="rounded border border-d-border bg-d-bg/70 p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <label
                          htmlFor={inputId}
                          className="block text-sm font-medium text-slate-100"
                        >
                          {assumption.label}
                        </label>
                        <p
                          id={`${inputId}-value`}
                          className="mt-0.5 font-mono text-xs text-gold-300"
                        >
                          {displayValue(value, assumption.unit)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => onReset(assumption.targetKey)}
                        disabled={!changed}
                        className="shrink-0 rounded px-2 py-1 text-[11px] text-d-muted hover:bg-d-hover hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
                        aria-label={`Reset ${assumption.label}`}
                      >
                        Reset
                      </button>
                    </div>

                    {showRangeInput && sliderControlStep !== null ? (
                      <input
                        id={inputId}
                        type="range"
                        min={sliderSpec.min}
                        max={sliderSpec.max}
                        step={sliderControlStep}
                        value={value}
                        aria-describedby={`${inputId}-value`}
                        onChange={(event) =>
                          onValueChange(
                            assumption.targetKey,
                            event.target.value,
                          )
                        }
                        className="mt-3 w-full accent-gold-500"
                      />
                    ) : (
                      <input
                        id={inputId}
                        type="number"
                        step="any"
                        inputMode="decimal"
                        value={activeNumberDraft?.value ?? value}
                        aria-describedby={`${inputId}-value`}
                        onFocus={() =>
                          setNumberEditorDraft({
                            targetKey: assumption.targetKey,
                            value,
                          })
                        }
                        onBlur={() => {
                          const committedValue =
                            normalizeFiniteDecimalDraft(
                              activeNumberDraft?.value ?? value,
                            );
                          if (
                            committedValue !== null &&
                            committedValue !== value
                          ) {
                            onValueChange(
                              assumption.targetKey,
                              committedValue,
                            );
                          }
                          setNumberEditorDraft((currentDraft) =>
                            currentDraft?.targetKey === assumption.targetKey
                              ? null
                              : currentDraft,
                          );
                        }}
                        onChange={(event) => {
                          const nextValue = event.target.value;
                          setNumberEditorDraft({
                            targetKey: assumption.targetKey,
                            value: nextValue,
                          });
                          const validValue =
                            normalizeFiniteDecimalDraft(nextValue);
                          if (
                            validValue !== null &&
                            validValue !== value
                          ) {
                            onValueChange(
                              assumption.targetKey,
                              validValue,
                            );
                          }
                        }}
                        className="mt-3 w-full rounded border border-d-border bg-d-card px-3 py-2 font-mono text-sm text-white focus:border-gold-400 focus:outline-none focus:ring-1 focus:ring-gold-400"
                      />
                    )}

                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
