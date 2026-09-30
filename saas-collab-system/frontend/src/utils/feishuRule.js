const fields = {
  notification: ['scene', 'recipient_user_ids', 'message', 'format'],
  report: ['report_type', 'recipient_user_ids', 'schedule', 'hour', 'format', 'filters'],
  approval: ['approval_type', 'recipient_user_ids'],
};

export function feishuRuleConfig(tab, editor, advanced = {}) {
  if (!advanced || typeof advanced !== 'object' || Array.isArray(advanced)) throw new Error('高级规则配置必须为JSON对象');
  const result = {};
  for (const key of fields[tab] || []) {
    const value = editor[key] ?? advanced[key];
    if (value !== undefined && value !== '') result[key] = value;
  }
  if (tab === 'report') result.hour = Number.parseInt(result.hour ?? 9, 10);
  if (result.approval_type === 'pricing') result.approval_type = 'price';
  return result;
}

export function feishuRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (!globalThis.crypto?.getRandomValues) throw new Error('请在安全HTTPS页面中执行投递');
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const value = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

export const feishuLabels = {
  configured: '已配置', unconfigured: '未配置', implemented: '已实现（权限待平台核对）',
  comprehensive: '综合报表', sales: '销售报表', inventory: '库存报表',
  daily: '每日', weekly: '每周一', monthly: '每月1日',
  text: '纯文本', card: '消息卡片', file: 'CSV附件',
  inventory_alert: '库存预警', business_alert: '经营预警', sync_failed: '同步失败',
  approval_pending: '审批待办', approval_result: '审批结果',
  pending: '待投递', processing: '处理中', success: '成功', failed: '失败', skipped: '已跳过', queued: '已入队',
  notification: '消息', report: '报表', approval: '审批通知', event: '回调事件',
  purchase: '采购审批', price: '价格审批', pricing: '价格审批', listing: '刊登审批',
  clearance: '清仓审批', finance: '财务审批', report_export: '报表导出审批',
};
