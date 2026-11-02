// Display-only ratio; persisted monetary facts retain their original decimals.
export function advertisingRatio(numerator, denominator) {
  if (numerator == null || denominator == null || numerator === '' || denominator === '') return '未知';
  const n = Number(numerator), d = Number(denominator);
  if (!Number.isFinite(n) || !Number.isFinite(d) || n < 0 || d <= 0) return '—';
  return (n / d).toFixed(2);
}
