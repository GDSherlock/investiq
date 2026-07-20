import { useMemo } from 'react';

import type { CalculationRunResponse } from '@/lib/calculation-api-types';
import {
  diffCalculationRunValues,
  formatTypedValue,
} from '@/lib/calculation-value-utils';

interface CalculationResultsDiffProps {
  baselineRun: CalculationRunResponse;
  overrideRun: CalculationRunResponse;
}

export function CalculationResultsDiff({
  baselineRun,
  overrideRun,
}: CalculationResultsDiffProps) {
  const changedValues = useMemo(
    () =>
      diffCalculationRunValues(baselineRun.values, overrideRun.values),
    [baselineRun.values, overrideRun.values],
  );

  return (
    <section className="rounded-lg border border-d-border bg-d-card p-6 shadow">
      <h3 className="text-lg font-semibold text-white">
        Persisted formula value changes
      </h3>
      {changedValues.length === 0 ? (
        <p className="mt-3 rounded border border-green-700/50 bg-green-900/20 p-3 text-sm text-green-300">
          Calculation completed successfully, but no persisted formula values
          changed.
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm text-d-muted">
            {changedValues.length} formula values changed, compared by full
            typed value and indexed by formula_cell_id.
          </p>
          <div className="mt-4 max-h-[36rem] overflow-auto rounded border border-d-border">
            <table className="min-w-full divide-y divide-d-border text-left text-xs">
              <thead className="sticky top-0 bg-d-bg text-d-muted">
                <tr>
                  <th className="px-3 py-2">Cell</th>
                  <th className="px-3 py-2">Baseline typed value</th>
                  <th className="px-3 py-2">Override typed value</th>
                  <th className="px-3 py-2">Validation</th>
                  <th className="px-3 py-2">Warnings</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-d-border text-slate-200">
                {changedValues.map(({ formulaCellId, baseline, override }) => (
                  <tr key={formulaCellId}>
                    <td className="px-3 py-2">
                      <div className="font-medium text-white">
                        {override.sheet_name}!{override.cell_address}
                      </div>
                      <div className="mt-1 max-w-48 break-all font-mono text-[10px] text-d-muted">
                        {formulaCellId}
                      </div>
                    </td>
                    <td className="px-3 py-2 font-mono">
                      {baseline.value?.value_type ?? 'null'}:{' '}
                      {formatTypedValue(baseline.value)}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      {override.value?.value_type ?? 'null'}:{' '}
                      {formatTypedValue(override.value)}
                    </td>
                    <td className="px-3 py-2">
                      {override.validation_status}
                    </td>
                    <td className="px-3 py-2">
                      {override.warnings.length > 0
                        ? override.warnings.join(', ')
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
