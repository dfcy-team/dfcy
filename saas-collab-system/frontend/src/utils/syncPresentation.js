export const resources = { platform_product: '平台商品', sales_order: '销售订单', refund_return: '退货退款', inventory_snapshot: '库存快照', inbound: '入库单', shipment: '出库单', settlement_bill: '财务流水', mock_record: '模拟记录' };
export const runStates = { queued: '排队中', skipped: '已跳过（未执行）', blocked: '配置阻塞', dispatch_failed: '派发未确认', running: '运行中', success: '成功', failed: '失败', cancelled: '已取消' };
export const schedules = { manual: '手动', hourly: '每小时', interval: '间隔', daily: '每日', weekly: '每周', cron: '定时' };
const runtimeStates = { queued: '排队中', running: '运行中', paused: '已暂停', backoff: '等待重试', credential_wait: '等待授权', completed: '已完成', success: '成功', failed: '失败', cancelled: '已取消' };
const deliveryStates = { present: '最近检查时队列存在', absent: '最近检查时队列未发现', unknown: '队列状态未知' };
const timezoneLabel = (value, historical = false) => !value ? (historical ? '时区未知' : '北京时间') : value === 'Asia/Shanghai' ? '北京时间' : value;
export function syncBeijingTime(value) {
  if (value == null || value === '') return '—';
  const date = new Date(typeof value === 'number' && Math.abs(value) < 1e12 ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return '—';
  const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(date);
  return parts;
}
export function syncPlanSummary(job = {}) {
  const kind = job.schedule_type || 'manual';
  const cadence = kind === 'interval' || kind === 'hourly' ? `每 ${job.interval_minutes ?? (kind === 'hourly' ? 60 : '—')} 分钟执行`
    : kind === 'manual' ? '手动执行' : `${schedules[kind] || '定时'}${job.local_time ? ` ${job.local_time}` : ''}${kind === 'weekly' && job.weekdays?.length ? ` · 周 ${job.weekdays.join('、')}` : ''}`;
  const scope = job.resource_type === 'platform_product' && job.product_order_backfill === 'order_missing_only' ? '仅补齐已落库订单缺失商品 ID，不按日期过滤'
    : job.resource_type === 'inventory_snapshot' ? '读取当前库存快照'
    : job.resource_type === 'platform_product' && job.product_full_sync ? '全量商品，不按时间过滤'
      : job.query_mode === 'range' ? `固定范围 ${rangeDate(job.range_start_at)} 至 ${rangeDate(job.range_end_at)}`
        : job.query_mode === 'incremental' && job.lookback_days != null ? `按${collectionBasis(job)}回看 ${job.lookback_days} 天`
          : ['inbound', 'shipment'].includes(job.resource_type) ? '不使用采集时间范围' : '未记录采集规则';
  const catchUp = job.catch_up === 'run_once' ? '错过后补跑一次' : job.catch_up === 'skip' ? '错过后跳过' : '未记录错过策略';
  const backfill = job.resource_type === 'platform_product' && job.product_order_backfill === 'catalog_and_order_missing' ? ' · 常规同步后补齐订单缺失商品 ID' : '';
  return `${cadence} · ${scope}${backfill} · ${timezoneLabel(job.timezone)} · ${catchUp}`;
}
export function syncHistoricalPlanSummary(snapshot) {
  if (!snapshot || typeof snapshot !== 'object' || !Object.keys(snapshot).length) return '未记录当次计划';
  const type = snapshot.schedule_type;
  if (!type) return `计划类型未知 · ${timezoneLabel(snapshot.timezone, true)} · 未记录采集规则`;
  const cadence = type === 'interval' || type === 'hourly' ? `每 ${snapshot.interval_minutes ?? (type === 'hourly' ? 60 : '—')} 分钟执行`
    : type === 'manual' ? '手动执行' : `${schedules[type] || '定时'}${snapshot.local_time ? ` ${snapshot.local_time}` : ''}${type === 'weekly' && snapshot.weekdays?.length ? ` · 周 ${snapshot.weekdays.join('、')}` : ''}`;
  const catchUp = snapshot.catch_up === 'run_once' ? '错过后补跑一次' : snapshot.catch_up === 'skip' ? '错过后跳过' : '未记录错过策略';
  return `${cadence} · ${timezoneLabel(snapshot.timezone, true)} · ${catchUp} · 未记录采集规则`;
}
function collectionBasis(job) {
  if (job.resource_type === 'refund_return') return '申请时间';
  if (job.resource_type === 'settlement_bill') return '平台记账时间';
  return job.collection_time_basis === 'created' ? '创建时间' : '更新时间';
}
function rangeDate(value) {
  if (!value) return '—';
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return value;
  const formatted = syncBeijingTime(value);
  return formatted === '—' ? '—' : formatted.slice(0, 10);
}
export function syncActualRange(source = {}) {
  return `${syncBeijingTime(source.time_from)} 至 ${syncBeijingTime(source.time_to)}`;
}
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
export function syncRuntimePresentation(runtime = {}) {
  if (!runtime || typeof runtime !== 'object') return '运行状态未知';
  const state = runtimeStates[runtime.state] || '运行状态未知';
  const parts = [state];
  if (runtime.queued_since) parts.push(`本次排队起点 ${syncTime(runtime.queued_since)}`);
  if (runtime.wait_seconds != null && Number.isFinite(Number(runtime.wait_seconds))) parts.push(`当前等待 ${Math.max(0, Math.floor(Number(runtime.wait_seconds)))} 秒`);
  if (runtime.last_progress_at) parts.push(`最近进度 ${syncTime(runtime.last_progress_at)}`);
  parts.push(deliveryStates[runtime.delivery_state] || deliveryStates.unknown);
  if (runtime.notice) parts.push(String(runtime.notice).replace(/(token|secret|password|authorization)\s*[:=]\s*\S+/ig, '$1=[已隐藏]').slice(0, 180));
  return parts.join(' · ');
}
export function syncError(value, code) {
  const text = String(value || '');
  if (/approved|readonly contract/i.test(text)) return '只读准入未通过，请检查生产准入配置。';
  if (/expired/i.test(text)) return '授权已过期，请更新主体授权。';
  if (/capability/i.test(text)) return '所需能力未开启，请检查能力矩阵。';
  if (/disabled/i.test(text)) return '任务已停用，请检查任务配置。';
  if (/ErrorDetail\(|Traceback|token|secret|password|authorization:/i.test(text)) return `执行失败（${code || '未提供错误码'}），请通过诊断编号排查。`;
  return text || (code ? `执行失败（${code}），请核对配置或查看同步异常。` : '—');
}
export function syncWorkspaceError(value, code) {
  const text = String(value || '');
  if (/timeout|超时/i.test(text)) return '同步数据读取超时，本次未显示数据；请缩小筛选范围或刷新重试。这不代表任务状态已变化。';
  if (/network error|failed to fetch|ERR_NETWORK/i.test(text)) return '网络连接失败，本次读取未完成；请恢复连接后重试。';
  return syncError(text || '同步数据读取失败，请刷新重试。', code);
}
