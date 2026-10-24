// Preferences contain column names only, never business rows or metric values.
export const columnsFor = view => view === 'products'
  ? [{ key: 'previous', label: '前期GMV' }, { key: 'change', label: '变化率' }, { key: 'volume', label: '销量' },
    { key: 'loss', label: '下降金额' }, { key: 'reason', label: '下降原因' }]
  : [{ key: 'previous', label: '前期GMV' }, { key: 'change', label: '变化率' }, { key: 'volume', label: '有效订单' },
    { key: 'loss', label: '下降金额' }, { key: 'ads', label: '广告花费' }, { key: 'roi', label: '整店ROI / 差值' }];

export function preferenceKey(user) {
  return user?.id && (user.tenant_id || user.tenant?.id)
    ? `sales.operations.columns.v1:${user.tenant_id || user.tenant.id}:${user.id}` : '';
}
export function readColumns(storage, key, view) {
  const defaults = columnsFor(view).map(item => item.key);
  if (!key) return defaults;
  try {
    const saved = JSON.parse(storage.getItem(key) || '{}')?.[view];
    return Array.isArray(saved) ? defaults.filter(name => saved.includes(name)) : defaults;
  } catch { return defaults; }
}
export function writeColumns(storage, key, view, selected) {
  if (!key) return;
  try {
    let current;
    try { current = JSON.parse(storage.getItem(key) || '{}'); } catch { current = {}; }
    if (!current || typeof current !== 'object' || Array.isArray(current)) current = {};
    const safe = Object.fromEntries(['stores', 'products'].map(mode => [mode, Array.isArray(current[mode])
      ? columnsFor(mode).map(c => c.key).filter(c => current[mode].includes(c)) : columnsFor(mode).map(c => c.key)]));
    safe[view] = columnsFor(view).map(c => c.key).filter(c => selected.includes(c));
    storage.setItem(key, JSON.stringify(safe));
  } catch { /* Storage can be disabled; the current in-memory selection still works. */ }
}
