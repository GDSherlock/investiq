export interface SensitivityTornadoGeometryRowInput {
  targetKey: string;
  lowDelta: number | null;
  highDelta: number | null;
}

export interface SensitivityTornadoGeometryInput {
  width: number;
  rowHeight: number;
  barHeight: number;
  rows: readonly SensitivityTornadoGeometryRowInput[];
}

export interface SensitivityTornadoEndpointGeometry {
  available: boolean;
  yCenter: number;
  barY: number;
  barHeight: number;
  barX: number | null;
  barWidth: number;
  markerX: number | null;
}

export interface SensitivityTornadoGeometryRow {
  targetKey: string;
  low: SensitivityTornadoEndpointGeometry;
  high: SensitivityTornadoEndpointGeometry;
}

export interface SensitivityTornadoGeometry {
  domain: readonly [number, number];
  extent: number;
  zeroX: number;
  rows: SensitivityTornadoGeometryRow[];
}

const FALLBACK_EXTENT = 1;

function availableDelta(value: number | null): value is number {
  return value !== null && Number.isFinite(value);
}

function endpointGeometry(
  value: number | null,
  yCenter: number,
  barHeight: number,
  zeroX: number,
  scale: (delta: number) => number,
): SensitivityTornadoEndpointGeometry {
  const barY = yCenter - barHeight / 2;
  if (!availableDelta(value)) {
    return {
      available: false,
      yCenter,
      barY,
      barHeight,
      barX: null,
      barWidth: 0,
      markerX: null,
    };
  }

  const markerX = scale(value);
  return {
    available: true,
    yCenter,
    barY,
    barHeight,
    barX: Math.min(zeroX, markerX),
    barWidth: Math.abs(markerX - zeroX),
    markerX,
  };
}

export function buildSensitivityTornadoGeometry({
  width,
  rowHeight,
  barHeight,
  rows,
}: SensitivityTornadoGeometryInput): SensitivityTornadoGeometry {
  const finiteDeltas = rows.flatMap((row) =>
    [row.lowDelta, row.highDelta].filter(availableDelta),
  );
  const largestMagnitude = Math.max(
    0,
    ...finiteDeltas.map((delta) => Math.abs(delta)),
  );
  const extent = largestMagnitude || FALLBACK_EXTENT;
  const usableWidth = Math.max(0, width);
  const zeroX = usableWidth / 2;
  const scale = (delta: number) => zeroX + (delta / extent) * zeroX;

  return {
    domain: [-extent, extent],
    extent,
    zeroX,
    rows: rows.map((row, index) => {
      const yCenter = index * rowHeight + rowHeight / 2;
      return {
        targetKey: row.targetKey,
        low: endpointGeometry(row.lowDelta, yCenter, barHeight, zeroX, scale),
        high: endpointGeometry(row.highDelta, yCenter, barHeight, zeroX, scale),
      };
    }),
  };
}
