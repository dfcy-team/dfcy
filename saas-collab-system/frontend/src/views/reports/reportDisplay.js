export const filterChoices = {
  sku_mode: [{ value: 'related', label: '合并同商品新旧编码' }, { value: 'source', label: '来源原始编码' }],
  inventory_type: [{ value: 'physical', label: '实体商品' }, { value: 'virtual', label: '虚拟商品' }, { value: 'unknown', label: '类型未提供' }],
  unmapped_only: [{ value: 'true', label: '仅未关联商品' }, { value: 'false', label: '全部商品' }],
  cost_status: [{ value: 'missing', label: '缺少成本' }, { value: 'confirmed', label: '已确认成本' }, { value: 'zero', label: '零成本' }],
  match_status: [{ value: 'matched', label: '已匹配' }, { value: 'order_only', label: '仅订单匹配' }, { value: 'unmatched', label: '未匹配' }, { value: 'conflict', label: '匹配冲突' }],
  fee_category: [{ value: 'income', label: '收入' }, { value: 'platform_fee', label: '平台费用' }, { value: 'logistics_fee', label: '物流费用' }, { value: 'discount', label: '优惠折扣' }, { value: 'refund', label: '退款' }, { value: 'tax', label: '税费' }, { value: 'adjustment', label: '调整项' }, { value: 'other', label: '未分类流水' }]
};
const states = { pending: '待处理', processing: '处理中', queued: '排队中', running: '执行中', completed: '已完成', failed: '失败', rejected: '已拒绝', cancelled: '已取消', shipped: '已发货', delivered: '已送达', confirmed: '已确认', unknown: '未提供', matched: '已匹配', unmatched: '未匹配', ambiguous: '待核对', order_only: '仅订单匹配', conflict: '匹配冲突', accepted: '已接受申请', paid: '已付款', open: '待处理', closed: '已关闭' };
const fees = { commission: '平台佣金', shipping: '物流费用', payment: '支付费用', refund: '退款', sales: '销售收入', advertising: '广告费用', tax: '税费', other: '未分类流水', adjustment: '调整项', income: '收入', platform_fee: '平台费用', logistics_fee: '物流费用', discount: '优惠折扣' };
export function displayReportValue(value, key = '') {
  if (value == null || value === '') return '未提供';
  if (key === 'sku_mode' || key === 'cost_status') return filterChoices[key].find(item => item.value === value)?.label || '口径待核对';
  if (key === 'inventory_type') return filterChoices.inventory_type.find(item => item.value === value)?.label || '类型待核对';
  if (key === 'status' || key === 'match_status') return states[value] || (/\p{Script=Han}/u.test(String(value)) ? String(value) : '状态待核对');
  if (key === 'fee_category') return fees[value] || (/\p{Script=Han}/u.test(String(value)) ? String(value) : '费用分类待核对');
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}
export function reportTimestamp(value) {
  if (!value) return '未提供';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '时间待核对';
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }).format(parsed);
}
export function reportError(message, fallback = '数据读取失败，请重试或检查数据接入状态。') {
  const text = String(message || '').replace(/^[A-Z][A-Z0-9_]+:\s*/, '');
  if (/\p{Script=Han}/u.test(text)) return text;
  if (/permission|scope|forbidden|403/i.test(text)) return '当前账号无权读取此报表，请核对业务权限和数据范围。';
  if (/timeout/i.test(text)) return '数据读取超时，请缩小筛选范围后重试。';
  return fallback;
}
export const reportFieldLabel = (dataset, key) => [...(dataset?.dimensions || []), ...(dataset?.metrics || [])].find(item => item.key === key)?.label || '未命名字段';
