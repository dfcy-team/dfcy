// Keep six-decimal server values intact; round only the presentation, HALF_UP.
export function warehouseMoney(value) {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value ?? ''));
  if (!match) return '—';
  const fraction = (match[3] || '').padEnd(3, '0');
  let cents = BigInt(match[2]) * 100n + BigInt(fraction.slice(0, 2));
  if (fraction[2] >= '5') cents += 1n;
  return `${match[1] && cents ? '-' : ''}${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`;
}

export function warehouseMoneyTotal(values) {
  let total = 0n;
  for (const value of values) {
    const match = /^(-?)(\d+)(?:\.(\d{1,6}))?$/.exec(String(value ?? ''));
    if (!match) return '—';
    const units = BigInt(match[2]) * 1000000n + BigInt((match[3] || '').padEnd(6, '0'));
    total += match[1] ? -units : units;
  }
  const absolute = total < 0n ? -total : total;
  return warehouseMoney(`${total < 0n ? '-' : ''}${absolute / 1000000n}.${String(absolute % 1000000n).padStart(6, '0')}`);
}
