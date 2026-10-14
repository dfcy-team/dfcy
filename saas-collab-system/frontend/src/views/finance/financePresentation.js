export const statusLabels = { imported: '已导入', matching: '匹配中', matched: '已匹配', exception: '异常', requested: '申请中', completed: '已完成', cancelled: '已取消', suggested: '待复核', confirmed: '已确认', rejected: '已拒绝', open: '待处理', resolved: '已解决', manual: '人工匹配', auto_suggested: '自动建议', amount_difference: '金额差异', currency_mismatch: '币种不一致', missing_receipt: '缺少到账' };
export const financeLabel = value => statusLabels[value] || value || '—';
export function recentFinancePeriod(now = new Date()) {
  const end = now.toISOString().slice(0, 10);
  const start = new Date(now);
  start.setUTCDate(start.getUTCDate() - 29);
  return [start.toISOString().slice(0, 10), end];
}
export function financeError(response) {
  const details = response?.data?.details ?? response?.data?.errors ?? response?.data;
  const rows = details?.rows;
  if (Array.isArray(rows)) return rows.slice(0, 20).map(x => `第 ${x.row} 行：${Object.entries(x.fields || {}).map(([field, messages]) => `${field} ${Array.isArray(messages) ? messages.join('；') : messages}`).join('；')}`).join(' / ');
  if (details && typeof details === 'object' && !Array.isArray(details)) {
    const messages = Object.entries(details).filter(([, value]) => typeof value === 'string' || Array.isArray(value)).map(([key, value]) => `${key}：${Array.isArray(value) ? value.join('；') : value}`);
    if (messages.length) return messages.join('；');
  }
  return response?.message || '读取失败，请重试。';
}
