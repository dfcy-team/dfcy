// One-use, in-memory handoff. A navigation never saves or submits an order.
let pending = null;
const MAX_AGE = 15 * 60 * 1000;
const positiveId = value => Number.isSafeInteger(Number(value)) && Number(value) > 0;
export function cockpitActorKey(owner) {
  const user = owner && typeof owner === 'object' ? owner : { id: owner };
  if (!positiveId(user.id)) return '';
  return JSON.stringify([Number(user.id), String(user.tenant_id ?? user.tenant?.id ?? ''), String(user.active_membership_id ?? '')]);
}
export function stageCockpitDraft(ownerId, input, now = Date.now()) {
  if (!cockpitActorKey(ownerId) || !positiveId(input?.parameters?.country_id)) throw new Error('账号或国家信息无效，请重新选择。');
  const p = input.parameters;
  if (!['cycle', 'season'].includes(p.source_kind) || !Array.isArray(input.rows) || !input.rows.length || input.rows.length > 100) throw new Error('请选择 1–100 个有正数建议的商品。');
  const seen = new Set();
  const lines = input.rows.map(row => {
    if (!positiveId(row.sku_id) || seen.has(Number(row.sku_id)) || !positiveId(row.suggested_quantity)) throw new Error('商品重复或建议数量无效，请重新核对。');
    seen.add(Number(row.sku_id));
    return { sku_id: Number(row.sku_id), sku: String(row.sku || ''), legacy_sku_code: String(row.legacy_sku_code || ''), product_name: String(row.product_name || ''), quantity: Number(row.suggested_quantity) };
  });
  pending = { ownerKey: cockpitActorKey(ownerId), createdAt: now, parameters: { country_id: Number(p.country_id), source_kind: p.source_kind, sales_start: p.sales_start, sales_end: p.sales_end, target_stock_sales_ratio: p.target_stock_sales_ratio, include_in_transit: Boolean(p.include_in_transit) }, lines };
}
export function consumeCockpitDraft(ownerId, now = Date.now()) {
  const value = pending;
  pending = null;
  if (!value || value.ownerKey !== cockpitActorKey(ownerId) || now < value.createdAt || now - value.createdAt > MAX_AGE) return null;
  return value;
}
