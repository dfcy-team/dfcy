// One-use, in-memory handoff. A navigation never saves or submits an order.
let pending = null;
const MAX_AGE = 15 * 60 * 1000;
const positiveId = value => Number.isSafeInteger(Number(value)) && Number(value) > 0;
export function cockpitActorKey(owner) {
  const user = owner && typeof owner === 'object' ? owner : { id: owner };
  const id = user.id ?? user.user_id;
  if (!positiveId(id)) return '';
  return JSON.stringify([Number(id), String(user.tenant_id ?? user.tenant?.id ?? ''), String(user.active_membership_id ?? '')]);
}
export function stageCockpitDraft(ownerId, input, now = Date.now()) {
  if (!cockpitActorKey(ownerId) || !positiveId(input?.parameters?.country_id)) throw new Error('账号或国家信息无效，请重新选择。');
  const p = input.parameters;
  const dailyJobId = typeof p.job_id === 'string' && p.job_id.startsWith('daily:') ? p.job_id.slice(6) : null;
  if (dailyJobId && !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(dailyJobId)) throw new Error('补货快照编号无效，请重新选择。');
  if (!['cycle', 'season'].includes(p.source_kind) || !Array.isArray(input.rows) || !input.rows.length || input.rows.length > 100) throw new Error('请选择 1–100 个有正数建议的商品。');
  const seen = new Set();
  const lines = input.rows.map(row => {
    if (!positiveId(row.sku_id) || seen.has(Number(row.sku_id)) || !positiveId(row.suggested_quantity)) throw new Error('商品重复或建议数量无效，请重新核对。');
    seen.add(Number(row.sku_id));
    return { sku_id: Number(row.sku_id), sku: String(row.sku_code || row.sku || ''), legacy_sku_code: String(row.legacy_sku_code || ''), product_name: String(row.product_name || ''), quantity: Number(row.suggested_quantity), ...(dailyJobId ? Object.fromEntries(['available_stock','in_transit_stock','pipeline','suggested_quantity','issues','source_snapshot_ids','source_run_ids','evidence'].filter(key=>row[key]!==undefined).map(key=>[key,JSON.parse(JSON.stringify(row[key]))])) : {}) };
  });
  pending = { ownerKey: cockpitActorKey(ownerId), createdAt: now, snapshot_job_id: dailyJobId, preview_token: input.preview_token || p.preview_token || input.preview?.preview_token, parameters: { country_id: Number(p.country_id), source_kind: p.source_kind, strategy_id: Number(p.strategy_id), algorithm_version: 'weighted_days_v1', sales_end: p.sales_end, activity_start: p.activity_start || null, activity_end: p.activity_end || null, activity_factor: Number(p.activity_factor || 1) }, lines };
}
export function consumeCockpitDraft(ownerId, now = Date.now()) {
  const value = pending;
  pending = null;
  if (!value || value.ownerKey !== cockpitActorKey(ownerId) || now < value.createdAt || now - value.createdAt > MAX_AGE) return null;
  return value;
}
