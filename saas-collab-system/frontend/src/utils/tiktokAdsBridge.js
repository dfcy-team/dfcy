export const ADS_RESULT_PATH = '/integrations/tiktok-ads/authorization-result';
export function validAdsSessionId(value) {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
    ? value.toLowerCase() : '';
}
export function adsResumeSessionId(search) {
  const params = new URLSearchParams(search);
  return [...params.keys()].length === 1 && params.getAll('session_id').length === 1
    ? validAdsSessionId(params.get('session_id')) : '';
}
export function adsSessionUrl(sessionId) {
  const id = validAdsSessionId(sessionId);
  return ADS_RESULT_PATH + (id ? `?session_id=${id}` : '');
}
export function captureAdsReceipt(location, history) {
  if (location.pathname !== ADS_RESULT_PATH) return null;
  const hash = location.hash;
  const search = location.search;
  history.replaceState(history.state, '', adsSessionUrl(adsResumeSessionId(search)));
  if (hash.length > 256) return null;
  const params = new URLSearchParams(hash.slice(1));
  if (search || [...params.keys()].length !== 2 || params.getAll('session_id').length !== 1
    || params.getAll('receipt_id').length !== 1
    || !validAdsSessionId(params.get('session_id'))
    || !/^[0-9a-f]{64}$/.test(params.get('receipt_id') || '')) return null;
  const sessionId = validAdsSessionId(params.get('session_id'));
  // Only the non-secret identifier survives reload. The one-use receipt stays in memory.
  history.replaceState(history.state, '', adsSessionUrl(sessionId));
  return { session_id: sessionId, receipt_id: params.get('receipt_id') };
}
let receipt = typeof window === 'undefined' ? null : captureAdsReceipt(window.location, window.history);
export function takeAdsReceipt() { const value = receipt; receipt = null; return value; }
export function navigateAdsBridge(value, navigate = (url) => window.location.assign(url)) {
  const target = new URL(value);
  const params = new URLSearchParams(target.hash.slice(1));
  if (target.origin !== 'https://dingfengchuangyu.com' || target.pathname !== '/saas-tk-ads/start'
    || target.username || target.password || target.search || [...params.keys()].length !== 1
    || target.hash.length > 6300 || params.getAll('ticket').length !== 1
    || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(params.get('ticket') || '')) throw new Error('Invalid Ads bridge');
  navigate(target.href);
}
