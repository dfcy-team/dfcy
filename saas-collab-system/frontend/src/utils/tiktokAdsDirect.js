import { createTikTokBrowserVerifier } from './tiktokBrowserBridge.js';

export const ADS_DIRECT_PATH = '/integrations/tiktok-ads/direct-callback';
export const ADS_DIRECT_CONTEXT_KEY = 'saas.tiktok.ads-direct-context.v1';
export const createAdsBrowserVerifier = createTikTokBrowserVerifier;

function validContext(context, origin) {
  if (!context || typeof context.browser_token !== 'string' || !context.browser_token || context.browser_token.length > 25000
      || !/^[A-Za-z0-9_-]{43}$/.test(context.verifier)
      || !Number.isFinite(Date.parse(context.expires_at)) || Date.parse(context.expires_at) <= Date.now()) return false;
  return origin.startsWith('https://') && context.callback_url === origin + ADS_DIRECT_PATH;
}

export function validateAdsOfficialUrl(value, callbackUrl) {
  if (typeof value !== 'string' || value.includes('#') || /^https?:\/\/[^/?#]*@/i.test(value)) throw new Error('Invalid Ads authorization URL');
  const url = new URL(value);
  const keys = [...url.searchParams.keys()];
  if (url.protocol !== 'https:' || url.hostname !== 'business-api.tiktok.com' || url.port
      || url.username || url.password || url.hash || url.pathname !== '/portal/auth'
      || keys.length !== 3 || keys.some((key) => !['app_id', 'state', 'redirect_uri'].includes(key))
      || !['app_id', 'state', 'redirect_uri'].every((key) => url.searchParams.getAll(key).length === 1 && url.searchParams.get(key))
      || url.searchParams.get('redirect_uri') !== callbackUrl) throw new Error('Invalid Ads authorization URL');
  return url.href;
}

export function prepareAdsDirect(direct, verifier, authorizationUrl, browser = window) {
  const context = { browser_token: direct?.browser_token, verifier, callback_url: direct?.callback_url, expires_at: direct?.expires_at };
  if (!validContext(context, browser.location.origin)) throw new Error('Invalid Ads direct context');
  const target = validateAdsOfficialUrl(authorizationUrl, context.callback_url);
  const serialized = JSON.stringify(context);
  browser.sessionStorage.setItem(ADS_DIRECT_CONTEXT_KEY, serialized);
  if (browser.sessionStorage.getItem(ADS_DIRECT_CONTEXT_KEY) !== serialized) throw new Error('Ads session storage unavailable');
  return target;
}
export function navigateAdsDirect(direct, verifier, authorizationUrl, browser = window) {
  browser.location.assign(prepareAdsDirect(direct, verifier, authorizationUrl, browser));
}
export function takeAdsManualCallback(value, browser = window) {
  if (typeof value !== 'string' || value.includes('#') || /^https?:\/\/[^/?#]*@/i.test(value)) throw new Error('回调地址无效。');
  const url = new URL(value);
  if (url.origin !== browser.location.origin || url.protocol !== 'https:' || url.username || url.password
      || url.pathname !== ADS_DIRECT_PATH || url.hash) throw new Error('仅接受本 SaaS 登记的广告回调地址。');
  const params = captureAdsDirectCallback(url, { replaceState() {} });
  if (!params) throw new Error('回调参数无效。');
  const context = JSON.parse(browser.sessionStorage.getItem(ADS_DIRECT_CONTEXT_KEY) || 'null');
  if (!validContext(context, browser.location.origin)) throw new Error('请先准备本次广告直连授权。');
  browser.sessionStorage.removeItem(ADS_DIRECT_CONTEXT_KEY);
  return { browser_token: context.browser_token, browser_verifier: context.verifier, callback_params: params };
}

export function captureAdsDirectCallback(location, history) {
  if (location.pathname !== ADS_DIRECT_PATH) return null;
  const search = location.search;
  const hash = location.hash;
  history.replaceState(history.state, '', ADS_DIRECT_PATH);
  if (!search || hash || search.length > 16000 || /%(?![0-9a-f]{2})/i.test(search)) return null;
  const limits = { auth_code: 4096, code: 4096, state: 4096, error: 1024, id: 40 };
  const params = {};
  for (const [key, value] of new URLSearchParams(search)) {
    if (!Object.hasOwn(limits, key) || Object.hasOwn(params, key) || !value || value.length > limits[key]
        || /[\u0000-\u001f\u007f\ufffd]/.test(value)) return null;
    params[key] = value;
  }
  if (!params.state || params.id && !/^[0-9]{5,40}$/.test(params.id)
      || Boolean(params.auth_code || params.code) === Boolean(params.error)) return null;
  return params;
}

let pending = typeof window === 'undefined' ? null : captureAdsDirectCallback(window.location, window.history);
let manualReturnParams = null;
export function clearAdsManualReturn() { manualReturnParams = null; pending = null; }
export function takeAdsManualReturnUrl(browser = window) {
  const params = manualReturnParams;
  manualReturnParams = null;
  if (!params || browser.location.pathname !== ADS_DIRECT_PATH || !browser.location.origin.startsWith('https://')) return '';
  return `${browser.location.origin}${ADS_DIRECT_PATH}?${new URLSearchParams(params)}`;
}
export function takeAdsDirectCallback(browser = window) {
  const params = pending;
  pending = null;
  manualReturnParams = null;
  if (browser.location.pathname !== ADS_DIRECT_PATH) return null;
  let raw = null;
  try {
    raw = browser.sessionStorage.getItem(ADS_DIRECT_CONTEXT_KEY);
    browser.sessionStorage.removeItem(ADS_DIRECT_CONTEXT_KEY);
  } catch { raw = null; /* Missing or uncleared proof storage never authorizes an exchange. */ }
  if (!params) return null;
  if (!raw) { manualReturnParams = params; return null; }
  try {
    const context = JSON.parse(raw);
    return validContext(context, browser.location.origin)
      ? { browser_token: context.browser_token, browser_verifier: context.verifier, callback_params: params } : null;
  } catch { return null; }
}
