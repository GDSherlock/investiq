import { useMemo } from 'react';

import {
  deriveSliderSpec,
  type SensitivityAssumption,
} from '@/lib/sensitivity-analysis';

interface SensitivityAssumptionPanelProps {
  assumptions: SensitivityAssumption[];
  overridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  maxDrivers: number;
  onValueChange: (targetKey: string, value: string) => void;
  onReset: (targetKey: string) => void;
  onResetAll: () => void;
  onToggleDriver: (targetKey: string, selected: boolean) => void;
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
  tornadoDriverKeys,
  maxDrivers,
  onValueChange,
  onReset,
  onResetAll,
  onToggleDriver,
}: SensitivityAssumptionPanelProps) {
  const selectedDrivers = useMemo(
    () => new Set(tornadoDriverKeys),
    [tornadoDriverKeys],
  );
  const groupedAssumptions = useMemo(
    () => categoryGroups(assumptions),
    [assumptions],
  );
  const driverLimitReached = selectedDrivers.size >= maxDrivers;
  const hasOverrides = Object.keys(overridesByTarget).length > 0;

  return (
    <aside className="rounded-lg border border-d-border bg-d-card shadow-sm lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-3 border-b border-d-border p-4">
        <div>
          <h2 className="text-base font-semibold text-white">Assumptions</h2>
          <p className="mt-1 text-xs text-d-muted">
            Canonical editable numeric parameters
          </p>
        </div>
        <button
          type="button"
          onClick={onResetAll}
          disabled={!hasOverrides}
          className="rounded border border-d-border px-2.5 py-1.5 text-xs text-slate-200 transition hover:border-gold-400 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          Reset all
        </button>
      </div>

      <div className="space-y-5 p-4 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto">
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
                const selected = selectedDrivers.has(assumption.targetKey);
                const rangeCapable = sliderSpec.kind === 'range';
                const onlySelectedDriver =
                  selected && selectedDrivers.size === 1;
                const inputId = `assumption-${assumption.targetKey}`;
                const driverId = `driver-${assumption.targetKey}`;
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

                    {sliderSpec.kind === 'range' ? (
                      <input
                        id={inputId}
                        type="range"
                        min={sliderSpec.min}
                        max={sliderSpec.max}
                        step={sliderSpec.step}
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
                        inputMode="decimal"
                        value={value}
                        aria-describedby={`${inputId}-value`}
                        onChange={(event) => {
                          const nextValue = event.target.value;
                          if (
                            nextValue !== '' &&
                            Number.isFinite(Number(nextValue))
                          ) {
                            onValueChange(
                              assumption.targetKey,
                              nextValue,
                            );
                          }
                        }}
                        className="mt-3 w-full rounded border border-d-border bg-d-card px-3 py-2 font-mono text-sm text-white focus:border-gold-400 focus:outline-none focus:ring-1 focus:ring-gold-400"
                      />
                    )}

                    <label
                      htmlFor={driverId}
                      className="mt-3 flex items-start gap-2 text-xs text-d-muted"
                    >
                      <input
                        id={driverId}
                        type="checkbox"
                        checked={selected}
                        disabled={
                          !rangeCapable ||
                          onlySelectedDriver ||
                          (!selected && driverLimitReached)
                        }
                        aria-label={`Include ${assumption.label} as tornado driver`}
                        aria-describedby={
                          !rangeCapable || onlySelectedDriver
                            ? `${driverId}-help`
                            : undefined
                        }
                        onChange={(event) =>
                          onToggleDriver(
                            assumption.targetKey,
                            event.target.checked,
                          )
                        }
                        className="mt-0.5 accent-gold-500"
                      />
                      <span>
                        Include as tornado driver
                        {!rangeCapable
                          ? ' — requires a non-zero value'
                          : onlySelectedDriver
                            ? ' — at least one non-zero driver required'
                            : !selected && driverLimitReached
                              ? ` — ${maxDrivers}-driver limit reached`
                              : ''}
                      </span>
                    </label>
                    {!rangeCapable || onlySelectedDriver ? (
                      <p
                        id={`${driverId}-help`}
                        className="mt-1 pl-6 text-[11px] text-amber-200"
                      >
                        {!rangeCapable
                          ? 'Enter a non-zero value before selecting this driver.'
                          : 'At least one non-zero driver required; select another eligible driver before removing this one.'}
                      </p>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </aside>
  );
}
