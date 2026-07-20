import type { CalculationInput } from '@/lib/calculation-api-types';
import { formatTypedValue } from '@/lib/calculation-value-utils';

interface CalculationInputPanelProps {
  inputs: CalculationInput[];
  selectedInputId: string;
  draftValue: string;
  disabled: boolean;
  onSelect: (targetId: string) => void;
  onDraftValueChange: (value: string) => void;
  onSubmit: () => void;
}

export function CalculationInputPanel({
  inputs,
  selectedInputId,
  draftValue,
  disabled,
  onSelect,
  onDraftValueChange,
  onSubmit,
}: CalculationInputPanelProps) {
  const editableNumericInputs = inputs.filter(
    (input) =>
      input.target_kind === 'parameter' &&
      input.editable &&
      input.current_value.value_type === 'number',
  );
  const selectedInput =
    editableNumericInputs.find((input) => input.target_id === selectedInputId) ??
    null;

  return (
    <section className="rounded-lg border border-d-border bg-d-card p-6 shadow">
      <h3 className="text-lg font-semibold text-white">Canonical inputs</h3>
      <p className="mt-1 text-sm text-d-muted">
        Values and units come directly from the calculation inputs API. Numbers
        remain strings until submitted.
      </p>

      {editableNumericInputs.length === 0 ? (
        <p className="mt-4 rounded border border-yellow-700/60 bg-yellow-900/20 p-3 text-sm text-yellow-300">
          No editable numeric canonical parameter is available for this model.
        </p>
      ) : (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="text-sm text-d-muted">
            Editable parameter
            <select
              value={selectedInputId}
              onChange={(event) => onSelect(event.target.value)}
              disabled={disabled}
              className="mt-1 w-full rounded border border-d-border bg-d-bg px-3 py-2 text-white disabled:opacity-60"
            >
              {editableNumericInputs.map((input) => (
                <option key={input.target_id} value={input.target_id}>
                  {input.label}
                  {input.unit ? ` (${input.unit})` : ''}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm text-d-muted">
            Override numeric string
            <input
              type="text"
              inputMode="decimal"
              value={draftValue}
              onChange={(event) => onDraftValueChange(event.target.value)}
              disabled={disabled}
              className="mt-1 w-full rounded border border-d-border bg-d-bg px-3 py-2 font-mono text-white disabled:opacity-60"
              placeholder="Enter a finite number"
            />
          </label>

          {selectedInput ? (
            <div className="md:col-span-2 rounded border border-d-border bg-d-bg p-3 text-sm">
              <dl className="grid gap-2 md:grid-cols-2">
                <div>
                  <dt className="text-d-muted">Current typed value</dt>
                  <dd className="font-mono text-white">
                    {formatTypedValue(selectedInput.current_value)}
                  </dd>
                </div>
                <div>
                  <dt className="text-d-muted">Unit</dt>
                  <dd className="text-white">{selectedInput.unit ?? '—'}</dd>
                </div>
                <div>
                  <dt className="text-d-muted">Category</dt>
                  <dd className="text-white">
                    {selectedInput.category ?? '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-d-muted">Target UUID</dt>
                  <dd className="break-all font-mono text-xs text-white">
                    {selectedInput.target_id}
                  </dd>
                </div>
              </dl>
            </div>
          ) : null}

          <button
            type="button"
            onClick={onSubmit}
            disabled={disabled || !selectedInput || draftValue.trim() === ''}
            className="md:col-span-2 rounded bg-gold-500 px-4 py-2.5 font-semibold text-white shadow-sm transition hover:bg-gold-600 disabled:cursor-not-allowed disabled:bg-gray-500 disabled:text-gray-300"
          >
            {disabled ? 'Calculation in progress…' : 'Run override calculation'}
          </button>
        </div>
      )}

      <details className="mt-5">
        <summary className="cursor-pointer text-sm font-medium text-white">
          Inspect all returned inputs ({inputs.length})
        </summary>
        <div className="mt-3 max-h-80 overflow-auto rounded border border-d-border">
          <table className="min-w-full divide-y divide-d-border text-left text-xs">
            <thead className="sticky top-0 bg-d-bg text-d-muted">
              <tr>
                <th className="px-3 py-2">Label</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Unit</th>
                <th className="px-3 py-2">Typed value</th>
                <th className="px-3 py-2">Target UUID</th>
                <th className="px-3 py-2">Access</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-d-border text-slate-200">
              {inputs.map((input) => (
                <tr key={`${input.target_kind}:${input.target_id}`}>
                  <td className="px-3 py-2">{input.label}</td>
                  <td className="px-3 py-2">{input.category ?? '—'}</td>
                  <td className="px-3 py-2">{input.unit ?? '—'}</td>
                  <td className="px-3 py-2 font-mono">
                    {input.current_value.value_type}:{' '}
                    {formatTypedValue(input.current_value)}
                  </td>
                  <td className="max-w-48 break-all px-3 py-2 font-mono">
                    {input.target_id}
                  </td>
                  <td className="px-3 py-2">
                    {input.editable &&
                    input.current_value.value_type === 'number'
                      ? 'editable'
                      : input.non_editable_reason ?? 'read-only'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
