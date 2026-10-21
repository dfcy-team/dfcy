export const TK_RESULT_PATH = '/integrations/tiktok/authorization-result';
export const TK_DIRECT_PATH = '/integrations/tiktok/shop-callback';
export const TK_DIRECT_CONTEXT_KEY = 'saas.tiktok.direct-context.v1';
export const isTikTokBindingId = (value) => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);

export function createTikTokBrowserVerifier(crypto = globalThis.crypto) {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function validateTikTokOfficialUrl(value) {
  if (typeof value !== 'string' || value.includes('#') || /^https?:\/\/[^/?#]*@/i.test(value)) throw new Error('TK 官方授权地址无效。');
  const url = new URL(value);
  const keys = [...url.searchParams.keys()];
  if (url.protocol !== 'https:' || url.port || url.username || url.password || url.hash
      || !['services.tiktokshop.com', 'services.us.tiktokshop.com'].includes(url.hostname)
      || url.pathname !== '/open/authorize' || keys.length !== 2
      || !['service_id', 'state'].every((key) => url.searchParams.getAll(key).length === 1 && url.searchParams.get(key))
      || keys.some((key) => !['service_id', 'state'].includes(key))) throw new Error('TK 官方授权地址无效。');
  return url.href;
}

function validDirectContext(context, origin) {
  if (!context || typeof context.browser_token !== 'string' || !context.browser_token || context.browser_token.length > 25000
      || !/^[A-Za-z0-9_-]{43}$/.test(context.verifier)
      || !Number.isFinite(Date.parse(context.expires_at)) || Date.parse(context.expires_at) <= Date.now()) return false;
  const url = new URL(context.callback_url);
  return url.protocol === 'https:' && url.origin === origin && url.pathname === TK_DIRECT_PATH
    && !url.search && !url.hash && !url.username && !url.password
    && context.callback_url === `${origin}${TK_DIRECT_PATH}`;
}

export function prepareTikTokDirect(direct, verifier, authorizationUrl, browser = window) {
  const target = validateTikTokOfficialUrl(authorizationUrl);
  const context = { browser_token: direct?.browser_token, verifier, callback_url: direct?.callback_url, expires_at: direct?.expires_at };
  if (!validDirectContext(context, browser.location.origin)) throw new Error('TK 回调会话无效，请重新发起授权。');
  // Storage is mandatory: never navigate or fall back to a popup without it.
  const serialized = JSON.stringify(context);
  browser.sessionStorage.setItem(TK_DIRECT_CONTEXT_KEY, serialized);
  if (browser.sessionStorage.getItem(TK_DIRECT_CONTEXT_KEY) !== serialized) throw new Error('无法保存本标签页授权会话。');
  return target;
}

export function navigateTikTokDirect(direct, verifier, authorizationUrl, browser = window) {
  browser.location.assign(prepareTikTokDirect(direct, verifier, authorizationUrl, browser));
}

export function takeTikTokManualCallback(value, browser = window) {
  if (typeof value !== 'string' || value.includes('#') || /^https?:\/\/[^/?#]*@/i.test(value)) throw new Error('回调地址无效。');
  const url = new URL(value);
  if (url.origin !== browser.location.origin || url.protocol !== 'https:' || url.username || url.password
      || url.pathname !== TK_DIRECT_PATH || url.hash) throw new Error('仅接受本 SaaS 登记的回调地址。');
  const params = captureTikTokDirectCallback(url, { replaceState() {} });
  if (!params) throw new Error('回调参数无效。');
  const raw = browser.sessionStorage.getItem(TK_DIRECT_CONTEXT_KEY);
  const context = JSON.parse(raw || 'null');
  if (!validDirectContext(context, browser.location.origin)) throw new Error('请先准备本次直连授权。');
  browser.sessionStorage.removeItem(TK_DIRECT_CONTEXT_KEY);
  return { browser_token: context.browser_token, browser_verifier: context.verifier, callback_params: params };
}

export function captureTikTokDirectCallback(location, history) {
  if (location.pathname !== TK_DIRECT_PATH) return null;
  const query = location.search;
  const fragment = location.hash;
  history.replaceState(history.state, '', TK_DIRECT_PATH);
  if (fragment || !query || query.length > 12000 || /%(?![0-9a-f]{2})/i.test(query)) return null;
  const limits = { code: 4096, state: 4096, error: 1024, app_key: 256, locale: 32, shop_region: 32 };
  const params = {};
  for (const [key, value] of new URLSearchParams(query)) {
    if (!Object.hasOwn(limits, key) || Object.hasOwn(params, key) || !value || value.length > limits[key]
        || /[\u0000-\u001f\u007f\ufffd]/.test(value)) return null;
    params[key] = value;
  }
  // Only the authenticated backend knows whether this session has a known shop.
  return Boolean(params.code) !== Boolean(params.error) ? params : null;
}

let pendingDirectCallback = typeof window === 'undefined' ? null : captureTikTokDirectCallback(window.location, window.history);
let manualReturnParams = null;

export function clearTikTokManualReturn() { manualReturnParams = null; pendingDirectCallback = null; }
export function takeTikTokManualReturnUrl(browser = window) {
  const params = manualReturnParams;
  manualReturnParams = null;
  if (!params || browser.location.pathname !== TK_DIRECT_PATH || !browser.location.origin.startsWith('https://')) return '';
  return `${browser.location.origin}${TK_DIRECT_PATH}?${new URLSearchParams(params)}`;
}

export function takeTikTokDirectCallback(browser = window) {
  const params = pendingDirectCallback;
  pendingDirectCallback = null;
  manualReturnParams = null;
  if (browser.location.pathname !== TK_DIRECT_PATH) return null;
  let raw = null;
  try {
    raw = browser.sessionStorage.getItem(TK_DIRECT_CONTEXT_KEY);
    browser.sessionStorage.removeItem(TK_DIRECT_CONTEXT_KEY);
  } catch { raw = null; /* Never exchange if proof storage cannot be read and cleared. */ }
  if (!params) return null;
  if (!raw) { manualReturnParams = params; return null; }
  try {
    const context = JSON.parse(raw);
    if (!validDirectContext(context, browser.location.origin)) return null;
    return { browser_token: context.browser_token, browser_verifier: context.verifier, callback_params: params };
  } catch { return null; }
}
const TK_START_URL = 'https://dingfengchuangyu.com/saas-tk/start';

export function captureTikTokReceipt(location, history) {
  if (location.pathname !== TK_RESULT_PATH) return '';
  const fragment = location.hash;
  const query = location.search;
  const resume = new URLSearchParams(query);
  if (!fragment && [...resume.keys()].length === 1 && isTikTokBindingId(resume.get('binding_id'))) return '';
  // Remove authorization material before router initialization or API requests.
  history.replaceState(history.state, '', TK_RESULT_PATH);
  if (query || fragment.length > 25100) return '';
  const values = new URLSearchParams(fragment.replace(/^#/, ''));
  if ([...values.keys()].length !== 1 || !values.has('receipt')) return '';
  const receipt = values.get('receipt');
  return /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(receipt) && receipt.length <= 25000 ? receipt : '';
}

let pendingReceipt = typeof window === 'undefined' ? '' : captureTikTokReceipt(window.location, window.history);

export function takeTikTokReceipt() {
  const receipt = pendingReceipt;
  pendingReceipt = '';
  return receipt;
}

export function navigateTikTokBridge(value, navigate = (url) => window.location.assign(url)) {
  const target = new URL(value);
  const fields = new URLSearchParams(target.hash.replace(/^#/, ''));
  if (target.origin + target.pathname !== TK_START_URL || target.search || target.username || target.password
      || [...fields.keys()].length !== 1 || !fields.has('ticket')
      || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(fields.get('ticket')) || target.hash.length > 25100) {
    throw new Error('TK 自动授权跳转地址无效，请联系管理员。');
  }
  // Same-tab navigation preserves this tab's SaaS sessionStorage login.
  navigate(target.href);
}
