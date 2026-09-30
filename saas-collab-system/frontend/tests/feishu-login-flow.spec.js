import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const mocks = vi.hoisted(() => ({
  config: vi.fn(), start: vi.fn(), qrMount: vi.fn(), login: vi.fn(), complete: vi.fn(), getMe: vi.fn(),
  replace: vi.fn(), route: { query: {} }, messageSuccess: vi.fn()
}));
vi.mock('../src/api/auth', () => ({ getFeishuLoginConfig: mocks.config, startFeishuLogin: mocks.start }));
vi.mock('../src/utils/feishuQrLogin', () => ({
  mountFeishuQr: mocks.qrMount,
  validateAuthorizeUrl: (value) => { try { const u = new URL(value); return u.origin === 'https://passport.feishu.cn' ? u : null; } catch { return null; } },
  feishuErrorMessages: { unbound: '此飞书账号尚未绑定企业账号，请使用账号密码登录并联系管理员。', provider_error: '飞书扫码登录暂时失败。', config_unavailable: '飞书扫码登录暂不可用，您仍可使用账号密码登录。' }
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ loading: false, errorMessage: '', login: mocks.login, completeFeishuLogin: mocks.complete }) }));
vi.mock('vue-router', () => ({ useRoute: () => mocks.route, useRouter: () => ({ replace: mocks.replace }) }));
vi.mock('element-plus', () => ({
  ElMessage: { success: mocks.messageSuccess },
  ElAlert: { props: ['title'], template: '<div>{{ title }}<slot /></div>' }, ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { props: ['label'], template: '<div>{{ label }}<slot /></div>' }, ElInput: { template: '<input />' }, ElButton: { template: '<button><slot /></button>' }
}));
import LoginView from '../src/views/auth/Login.vue';

describe('Feishu login page flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.route.query = {};
    mocks.config.mockResolvedValue({ success: true, data: { enabled: false } });
    mocks.start.mockResolvedValue({ success: false, code: 'config_unavailable' });
    mocks.qrMount.mockResolvedValue(vi.fn());
    mocks.login.mockResolvedValue({ success: false, message: 'bad credentials' });
    mocks.complete.mockResolvedValue({ success: false, code: 'provider_error' });
  });

  it('keeps password login available when QR login is disabled and reports an unbound callback', async () => {
    mocks.route.query = { feishu_error: 'unbound' };
    const wrapper = mount(LoginView, { global: { stubs: { 'el-form': true, 'el-form-item': true, 'el-input': true, 'el-button': true, 'el-alert': true } } });
    await flushPromises();
    expect(wrapper.text()).toContain('此飞书账号尚未绑定企业账号');
    expect(wrapper.text()).toContain('用户名');
    expect(wrapper.text()).toContain('密码');
    expect(mocks.complete).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('preserves the full authorize URL, including state, when initializing the official QR SDK', async () => {
    const fullUrl = 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=synthetic-client&redirect_uri=https%3A%2F%2Fapp.example%2Flogin&response_type=code&state=synthetic-state&scope=contact';
    mocks.config.mockResolvedValue({ success: true, data: { enabled: true } });
    mocks.start.mockResolvedValue({ success: true, data: { authorize_url: fullUrl } });
    const wrapper = mount(LoginView, { global: { stubs: { 'el-form': true, 'el-form-item': true, 'el-input': true, 'el-button': true, 'el-alert': true } } });
    await flushPromises();
    expect(mocks.qrMount).toHaveBeenCalledWith(expect.objectContaining({ authorizeUrl: fullUrl, id: 'feishu-qr-login' }));
    wrapper.unmount();
  });

  it('rejects forged SDK messages unless both SDK matchers and iframe source agree', async () => {
    const { validFeishuMessage } = await vi.importActual('../src/utils/feishuQrLogin');
    const iframe = { contentWindow: {} };
    const sdk = { matchOrigin: vi.fn(() => true), matchData: vi.fn(() => true) };
    const event = { origin: 'https://passport.feishu.cn', source: iframe.contentWindow, data: { tmp_code: 'synthetic-code' } };
    expect(validFeishuMessage(event, iframe.contentWindow, sdk)).toBe('synthetic-code');
    expect(validFeishuMessage({ ...event, source: {} }, iframe.contentWindow, sdk)).toBeNull();
    sdk.matchOrigin.mockReturnValue(false);
    expect(validFeishuMessage(event, iframe.contentWindow, sdk)).toBeNull();
  });

  it('removes the message listener when the QR mount times out', async () => {
    vi.useFakeTimers();
    const { mountFeishuQr } = await vi.importActual('../src/utils/feishuQrLogin');
    const container = document.createElement('div');
    window.QRLogin = vi.fn(() => ({ matchOrigin: () => true, matchData: () => true }));
    const onError = vi.fn();
    const remove = vi.spyOn(window, 'removeEventListener');
    const stop = await mountFeishuQr({ id: 'synthetic-qr', container, authorizeUrl: 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=x&redirect_uri=https%3A%2F%2Fapp.example&response_type=code&state=s', onError });
    await vi.advanceTimersByTimeAsync(300000);
    expect(onError).toHaveBeenCalledWith('expired');
    expect(remove).toHaveBeenCalledWith('message', expect.any(Function));
    stop();
    remove.mockRestore();
    delete window.QRLogin;
    vi.useRealTimers();
  });
});
