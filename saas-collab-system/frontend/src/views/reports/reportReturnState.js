const STORAGE_PREFIX = 'saas-collab.report-return.v1';

function scopeKey(user) {
  const tenantId = user?.tenant_id ?? user?.tenant?.id;
  const userId = user?.user_id ?? user?.id ?? user?.username;
  if (tenantId == null || userId == null) return '';
  return `${STORAGE_PREFIX}:${encodeURIComponent(String(tenantId))}:${encodeURIComponent(String(userId))}`;
}

export function saveReportReturnConfig(user, config) {
  const key = scopeKey(user);
  if (!key || !config || typeof config !== 'object') return;
  try {
    globalThis.sessionStorage?.setItem(key, JSON.stringify(config));
  } catch (_error) { /* Storage may be unavailable in restricted browser contexts. */ }
}

export function takeReportReturnConfig(user) {
  const key = scopeKey(user);
  if (!key) return null;
  try {
    const value = globalThis.sessionStorage?.getItem(key);
    globalThis.sessionStorage?.removeItem(key);
    const config = value ? JSON.parse(value) : null;
    return config && typeof config === 'object' && !Array.isArray(config) ? config : null;
  } catch (_error) {
    return null;
  }
}
