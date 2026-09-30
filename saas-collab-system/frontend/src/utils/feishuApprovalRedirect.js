const key = 'saas-collab.feishu-approval-return.v1';
const valid = (value) => typeof value === 'string' && /^\/workflow\/approvals\/[1-9]\d*$/.test(value);

export function rememberApprovalReturn(value, storage = globalThis.sessionStorage, now = Date.now()) {
  try {
    storage.removeItem(key);
    if (valid(value)) storage.setItem(key, JSON.stringify({ path: value, expires: now + 300000 }));
  } catch { /* Browser storage is optional; normal password login remains available. */ }
}

export function takeApprovalReturn(storage = globalThis.sessionStorage, now = Date.now()) {
  try {
    const raw = storage.getItem(key); storage.removeItem(key);
    const value = JSON.parse(raw);
    return valid(value?.path) && Number.isFinite(value.expires) && value.expires > now && value.expires <= now + 300000 ? value.path : undefined;
  } catch { return undefined; }
}
