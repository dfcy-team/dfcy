export const amountSeries = [
  { key: 'gross_sales', label: '销售额', color: '#6952d9' },
  { key: 'net_sales', label: '净销售额', color: '#008978' },
  { key: 'refund_amount', label: '退款额', color: '#bf6500' }
];

export function completedDateRange(days, now = new Date()) {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - days + 1);
  const format = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  return [format(start), format(end)];
}

function number(value) {
  if (!['string', 'number'].includes(typeof value) || String(value).trim() === '') return null;
  return Number.isFinite(Number(value)) ? Number(value) : null;
}

// Missing source values remain missing; currencies are never added together.
export function aggregateTrend(rows = [], currency, series = amountSeries) {
  const buckets = new Map();
  for (const row of rows) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date || '')) continue;
    const date = new Date(`${row.date}T00:00:00Z`);
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== row.date) continue;
    const key = date.toISOString().slice(0, 10);
    if (!buckets.has(key)) buckets.set(key, { date: key, ...Object.fromEntries(series.map(item => [item.key, null])) });
    const bucket = buckets.get(key);
    for (const { key: field } of series) {
      const value = number(row[field]?.[currency]);
      if (value !== null) bucket[field] = (bucket[field] ?? 0) + value;
    }
  }
  return [...buckets.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export function chartGeometry(rows, keys, { width = 1000, integer = false } = {}) {
  const values = rows.flatMap(row => keys.map(key => row[key])).filter(value => value !== null && Number.isFinite(value));
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const span = max - min || 1;
  const lower = integer ? Math.floor(Math.min(0, min) / 5) * 5 : min < 0 ? min - span * .08 : 0;
  const upper = integer ? Math.max(5, Math.ceil(max * 1.08 / 5) * 5) : max + span * .08 || 1;
  const x = index => 76 + (rows.length > 1 ? index / (rows.length - 1) : .5) * (width - 120);
  const y = value => 270 - (value - lower) / (upper - lower) * 238;
  const ticks = Array.from({ length: 6 }, (_, index) => {
    const value = lower + (upper - lower) * index / 5;
    return { value, y: y(value) };
  });
  const paths = keys.map(key => {
    let connected = false;
    const path = rows.map((row, index) => {
      if (row[key] === null) { connected = false; return ''; }
      const command = connected ? 'L' : 'M'; connected = true;
      return `${command}${x(index)},${y(row[key])}`;
    }).join(' ');
    return { key, path, points: rows.flatMap((row, index) => row[key] === null ? [] : [{ x: x(index), y: y(row[key]), date: row.date, value: row[key] }]) };
  });
  return { ticks, paths, x, hasValues: values.length > 0 };
}
