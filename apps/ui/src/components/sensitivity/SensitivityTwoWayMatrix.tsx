import type { SensitivityMatrixView } from '@/lib/sensitivity-analysis';

interface SensitivityTwoWayMatrixProps {
  matrix: SensitivityMatrixView | null;
  outputLabel: string;
  unavailableReason?: string | null;
  formatAxisValue: (targetKey: string, value: string) => string;
  formatOutputValue: (value: number | null) => string;
}

export function SensitivityTwoWayMatrix({
  matrix,
  outputLabel,
  unavailableReason = null,
  formatAxisValue,
  formatOutputValue,
}: SensitivityTwoWayMatrixProps) {
  if (matrix === null) {
    return (
      <p className="rounded border border-d-border bg-d-bg p-4 text-sm text-d-muted">
        {unavailableReason ??
          'Run an analysis to build the automatic matrix from the two highest impact assumptions.'}
      </p>
    );
  }

  const availableValues = matrix.rows.flatMap((row) =>
    row.cells.flatMap((cell) =>
      cell.numericValue === null ? [] : [cell.numericValue],
    ),
  );
  const minimum =
    availableValues.length > 0 ? Math.min(...availableValues) : null;
  const maximum =
    availableValues.length > 0 ? Math.max(...availableValues) : null;

  const heatBackground = (value: number | null): string | undefined => {
    if (value === null || minimum === null || maximum === null) {
      return undefined;
    }
    const normalized =
      maximum === minimum ? 0.5 : (value - minimum) / (maximum - minimum);
    return `rgba(197, 160, 89, ${0.06 + normalized * 0.18})`;
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] border-collapse text-sm">
        <caption className="sr-only">
          {outputLabel} by {matrix.rowLabel} and {matrix.columnLabel}
        </caption>
        <thead>
          <tr className="border-b border-d-border text-d-muted">
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {matrix.rowLabel} / {matrix.columnLabel}
            </th>
            {matrix.columnValues.map((columnValue) => (
              <th
                key={columnValue}
                scope="col"
                className="px-3 py-2 text-right font-mono font-medium"
              >
                {formatAxisValue(matrix.columnTargetKey, columnValue)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row) => (
            <tr key={row.value} className="border-b border-d-border">
              <th
                scope="row"
                className="px-3 py-2 text-left font-mono font-medium text-slate-200"
              >
                {formatAxisValue(matrix.rowTargetKey, row.value)}
              </th>
              {row.cells.map((cell) => {
                const value = formatOutputValue(cell.numericValue);
                const metadata = cell.calculationRunId
                  ? `Run ${cell.calculationRunId}`
                  : 'No calculation run';
                const reason = cell.unavailableReason
                  ? `; ${cell.unavailableReason}`
                  : '';
                const warnings =
                  cell.warnings.length > 0
                    ? `; ${cell.warnings.join('; ')}`
                    : '';
                return (
                  <td
                    key={`${cell.rowValue}:${cell.columnValue}`}
                    className={`px-3 py-2 text-right font-mono ${
                      cell.numericValue === null
                        ? 'text-amber-200'
                        : 'font-semibold text-white'
                    }`}
                    style={{
                      backgroundColor: heatBackground(cell.numericValue),
                    }}
                    title={`${metadata}${reason}${warnings}`}
                    aria-label={`${matrix.rowLabel} ${formatAxisValue(
                      matrix.rowTargetKey,
                      row.value,
                    )}, ${matrix.columnLabel} ${formatAxisValue(
                      matrix.columnTargetKey,
                      cell.columnValue,
                    )}: ${value}. ${metadata}${reason}${warnings}`}
                  >
                    <span>
                      {cell.numericValue === null ? 'Unavailable' : value}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
