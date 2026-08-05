export function defaultMonteCarloSpread(value: number): number {
  return Math.max(Math.abs(value) * 0.1, 0.000001);
}
