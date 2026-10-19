export const TK_RESULT_PATH = '/integrations/tiktok/authorization-result';
const TK_START_URL = 'https://dingfengchuangyu.com/saas-tk/start';

export function captureTikTokReceipt(location, history) {
  if (location.pathname !== TK_RESULT_PATH) return '';
  const fragment = location.hash;
  const query = location.search;
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
