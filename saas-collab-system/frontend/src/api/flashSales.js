import request from './request';

export async function flashRequest(path, method = 'get', data, params) {
  const result = await request({ url: `/api/internal/marketing/flash-sales/${path}`, method, data, params, timeout: 60000, noMockFallback: true });
  if (!result?.success) throw new Error(result?.message || '闪购请求未完成');
  return result.data;
}
export const taskLabels = { queued: '排队中', running: '处理中', waiting: '等待重试', confirming: '待核对', succeeded: '已完成', failed: '未完成', stopped: '已停止', missed: '已错过，未补跑' };
export const finished = (task) => ['succeeded', 'failed', 'stopped', 'missed'].includes(task.status);
export function flashTime(value, zone = 'Asia/Shanghai') {
  if (!value) return '—';
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return '—';
  try { return new Intl.DateTimeFormat('zh-CN', { timeZone: zone, dateStyle: 'short', timeStyle: 'short', hour12: false }).format(date); }
  catch { return '时区无效'; }
}
export function copyRows(rows, includeDisabled = false) { return rows.map(row => ({...row, participate: row.status === 1 || includeDisabled})); }
export function copyPayload(rows) { return rows.map(({item_id, model_id, price, stock, purchase_limit, participate}) => ({item_id, model_id, price, stock, purchase_limit, participate})); }
