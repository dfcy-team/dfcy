export const FEISHU_AUTHORIZE_URL = 'https://passport.feishu.cn/suite/passport/oauth/authorize';
export const FEISHU_SDK_URL = 'https://lf-package-cn.feishucdn.com/obj/feishu-static/lark/passport/qrcode/LarkSSOSDKWebQRCode-1.0.3.js';
const PASSPORT_ORIGIN = 'https://passport.feishu.cn';

export function validFeishuMessage(event, iframeWindow, instance) {
  if (!event || event.origin !== PASSPORT_ORIGIN || !iframeWindow || event.source !== iframeWindow
    || typeof instance?.matchOrigin !== 'function' || typeof instance?.matchData !== 'function') return null;
  try {
    if (!instance.matchOrigin(event.origin) || !instance.matchData(event.data)) return null;
  } catch { return null; }
  const data = event.data;
  const code = data && typeof data === 'object' && !Array.isArray(data) ? data.tmp_code : null;
  return typeof code === 'string' && code.length > 0 && code.length <= 2048 ? code : null;
}

function loadSdk(timeoutMs = 10000) {
  if (typeof window.QRLogin === 'function') return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${FEISHU_SDK_URL}"]`);
    const script = existing || document.createElement('script');
    const cleanup = () => {
      window.clearTimeout(timeout);
      script.removeEventListener('load', loaded);
      script.removeEventListener('error', failed);
    };
    const failed = () => {
      cleanup();
      script.remove();
      reject(new Error('sdk_unavailable'));
    };
    const loaded = () => {
      if (typeof window.QRLogin !== 'function') return failed();
      cleanup();
      resolve();
    };
    const timeout = window.setTimeout(failed, timeoutMs);
    script.addEventListener('load', loaded, { once: true });
    script.addEventListener('error', failed, { once: true });
    if (!existing) {
      script.src = FEISHU_SDK_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  });
}

export function validateAuthorizeUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.hostname !== 'passport.feishu.cn' || url.port || url.pathname !== '/suite/passport/oauth/authorize'
      || url.username || url.password || url.hash || url.searchParams.has('username') || url.searchParams.has('password')) return null;
    for (const key of ['client_id', 'state', 'redirect_uri']) if (!url.searchParams.get(key)) return null;
    if (url.searchParams.get('response_type') !== 'code') return null;
    return url;
  } catch { return null; }
}

export async function mountFeishuQr({ id, container, authorizeUrl, onError, isActive = () => true }) {
  let active = true;
  let timer;
  let instance;
  const target = validateAuthorizeUrl(authorizeUrl);
  if (!target) { onError?.('provider_error'); return () => {}; }
  const listener = (event) => {
    const iframe = container.querySelector('iframe');
    if (!active || !instance || typeof instance.matchOrigin !== 'function' || typeof instance.matchData !== 'function') return;
    const code = validFeishuMessage(event, iframe?.contentWindow, instance);
    if (!code) return;
    active = false;
    window.clearTimeout(timer);
    window.removeEventListener('message', listener);
    const goto = `${target.toString()}&tmp_code=${encodeURIComponent(code)}`;
    window.location.assign(goto);
  };
  try {
    await loadSdk();
    if (!active || !isActive()) { active = false; return () => {}; }
    window.addEventListener('message', listener);
    instance = window.QRLogin({ id, goto: target.toString(), width: 300, height: 300, style: '' });
    if (typeof instance?.matchOrigin !== 'function' || typeof instance?.matchData !== 'function') throw new Error('invalid_sdk');
    timer = window.setTimeout(() => {
      if (!active) return;
      active = false;
      window.removeEventListener('message', listener);
      onError?.('expired');
    }, 300000);
  } catch {
    window.removeEventListener('message', listener);
    if (active && isActive()) onError?.('config_unavailable');
  }
  return () => {
    active = false;
    window.clearTimeout(timer);
    window.removeEventListener('message', listener);
  };
}

export const feishuErrorMessages = {
  expired: '二维码已过期，请刷新后重试。',
  state_invalid: '登录请求已失效，请刷新二维码后重试。',
  unbound: '此飞书账号尚未绑定企业账号，请使用账号密码登录并联系管理员。',
  account_unavailable: '企业账号当前不可用，请联系管理员。',
  provider_error: '飞书登录暂时失败，请稍后重试或使用账号密码登录。',
  config_unavailable: '飞书扫码登录暂不可用，您仍可使用账号密码登录。',
  denied: '您已取消飞书登录。'
};
