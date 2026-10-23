export const hasNumber = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
export const amount = value => hasNumber(value) ? Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
export const percent = value => hasNumber(value) ? `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)}%` : '—';
export const delta = value => hasNumber(value) ? `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)}` : '—';
export function dateRange(days, now = new Date()) {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
  const end = new Date(`${today}T00:00:00Z`); end.setUTCDate(end.getUTCDate() - 1);
  const start = new Date(end); start.setUTCDate(start.getUTCDate() - days + 1);
  return { date_from: start.toISOString().slice(0, 10), date_to: end.toISOString().slice(0, 10) };
}
export function validRange(filters) {
  const from = Date.parse(filters.date_from), to = Date.parse(filters.date_to);
  if (!Number.isFinite(from) || !Number.isFinite(to) || from > to) return '请选择有效的起止日期。';
  if ((to - from) / 86400000 >= 31) return '单次最多查询31天，请缩小日期范围。';
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  return filters.date_to >= today ? '经营日报仅比较已结束日期；今日同时段快照尚未就绪。' : '';
}
