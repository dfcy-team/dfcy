export const resources = { platform_product: '平台商品', sales_order: '销售订单', refund_return: '退货退款', inventory_snapshot: '库存快照', inbound: '入库单', shipment: '出库单', mock_record: '模拟记录' };
export const runStates = { queued: '排队中', skipped: '已跳过（未执行）', blocked: '配置阻塞', dispatch_failed: '派发未确认', running: '运行中', success: '成功', failed: '失败', cancelled: '已取消' };
export const schedules = { manual: '手动', hourly: '每小时', interval: '间隔', daily: '每日', weekly: '每周', cron: '定时' };
export function syncTime(value) {
  if (value == null || value === '') return '—';
  const date = new Date(typeof value === 'number' && Math.abs(value) < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().replace('T', ' ').slice(0, 19);
}
export function syncCollectionDate(seconds) {
  if (seconds == null || seconds === '' || !Number.isFinite(Number(seconds))) return '—';
  const date = new Date((Number(seconds) + 8 * 3600) * 1000);
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().slice(0, 10);
}
export function syncCount(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN'); }
export function syncError(value, code) {
  const text = String(value || '');
  if (/approved|readonly contract/i.test(text)) return '只读准入未通过，请检查生产准入配置。';
  if (/expired/i.test(text)) return '授权已过期，请更新主体授权。';
  if (/capability/i.test(text)) return '所需能力未开启，请检查能力矩阵。';
  if (/disabled/i.test(text)) return '任务已停用，请检查任务配置。';
  if (/ErrorDetail\(|Traceback|token|secret|password|authorization:/i.test(text)) return `执行失败（${code || '未提供错误码'}），请通过诊断编号排查。`;
  return text || (code ? `执行失败（${code}），请核对配置或查看同步异常。` : '—');
}
