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
  feishuErrorMessages: { unbound: '此飞书账号尚未绑定系统账号，请使用账号密码登录，并在个人设置中绑定飞书账号。', provider_error: '飞书扫码登录暂时失败。', config_unavailable: '飞书扫码登录暂不可用，您仍可使用账号密码登录。' }
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ loading: false, errorMessage: '', login: mocks.login, completeFeishuLogin: mocks.complete }) }));
vi.mock('vue-router', () => ({ useRoute: () => mocks.route, useRouter: () => ({ replace: mocks.replace }) }));
vi.mock('element-plus', () => ({
  ElMessage: { success: mocks.messageSuccess },
  ElAlert: { props: ['title'], template: '<div>{{ title }}<slot /></div>' }, ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { props: ['label'], template: '<div>{{ label }}<slot /></div>' }, ElInput: { template: '<input />' }, ElButton: { template: '<button><slot /></button>' }
}));
import LoginView from '../src/views/auth/Login.vue';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('Feishu login page flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    mocks.route.query = {};
    mocks.config.mockResolvedValue({ success: true, data: { enabled: false } });
    mocks.start.mockResolvedValue({ success: false, code: 'config_unavailable' });
    mocks.qrMount.mockResolvedValue(vi.fn());
    mocks.login.mockResolvedValue({ success: false, message: 'bad credentials' });
    mocks.complete.mockResolvedValue({ success: false, code: 'provider_error' });
    mocks.replace.mockResolvedValue(undefined);
  });

  it('hides credentials on the first callback render, before URL cleanup finishes', async () => {
    const cleanup = deferred();
    mocks.route.query = { feishu: 'complete' };
    mocks.replace.mockReturnValue(cleanup.promise);
    const wrapper = mount(LoginView);
    expect(wrapper.find('[role="status"]').exists()).toBe(true);
    expect(wrapper.find('.password-login').exists()).toBe(false);
    expect(wrapper.find('.feishu-login').exists()).toBe(false);
    expect(mocks.complete).not.toHaveBeenCalled();
    wrapper.unmount();
    cleanup.resolve();
    await flushPromises();
    expect(mocks.complete).not.toHaveBeenCalled();
  });

  it.each(['orders', 'returns'])('restores the %s reminder after a QR callback without redirect', async (source) => {
    const destination = `/sales-management/${source}?reminder_id=1&reminder_membership=0`;
    mocks.route.query = { redirect: destination };
    mocks.config.mockResolvedValue({ success: true, data: { enabled: true } });
    mocks.start.mockResolvedValue({ success: true, data: { authorize_url: 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=synthetic&state=synthetic' } });
    const login = mount(LoginView);
    await flushPromises();
    expect(mocks.qrMount).toHaveBeenCalledTimes(1);
    login.unmount();

    mocks.route.query = { feishu: 'complete' };
    mocks.complete.mockResolvedValue({ success: true });
    const callback = mount(LoginView);
    await flushPromises();
    expect(mocks.replace).toHaveBeenLastCalledWith(destination);
    expect(sessionStorage.getItem('saas-collab.feishu-approval-return.v1')).toBeNull();
    callback.unmount();
  });

  it('keeps only the progress screen while completing login and opening the destination', async () => {
    const completion = deferred();
    const navigation = deferred();
    mocks.route.query = { feishu: 'complete', redirect: '/reports?owner=self' };
    mocks.complete.mockReturnValue(completion.promise);
    mocks.replace.mockImplementation((destination) => typeof destination === 'string' ? navigation.promise : Promise.resolve());
    const wrapper = mount(LoginView);
    await flushPromises();
    expect(mocks.complete).toHaveBeenCalledTimes(1);
    expect(wrapper.find('.login-panel').attributes('aria-busy')).toBe('true');
    expect(wrapper.find('.password-login').exists()).toBe(false);
    expect(wrapper.find('.login-panel__boundary').exists()).toBe(false);
    expect(mocks.config).not.toHaveBeenCalled();
    expect(mocks.start).not.toHaveBeenCalled();
    expect(mocks.login).not.toHaveBeenCalled();
    completion.resolve({ success: true });
    await flushPromises();
    expect(mocks.replace).toHaveBeenLastCalledWith('/reports?owner=self');
    expect(wrapper.find('[role="status"]').exists()).toBe(true);
    expect(wrapper.find('.password-login').exists()).toBe(false);
    navigation.resolve();
    await flushPromises();
    expect(wrapper.find('.password-login').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each(['failure response', 'unexpected rejection'])('restores login choices after a %s', async (failure) => {
    const completion = deferred();
    mocks.route.query = { feishu: 'complete' };
    mocks.complete.mockReturnValue(completion.promise);
    const wrapper = mount(LoginView);
    await flushPromises();
    expect(wrapper.find('.password-login').exists()).toBe(false);
    if (failure === 'failure response') completion.resolve({ success: false, code: 'provider_error' });
    else completion.reject(new Error('synthetic completion failure'));
    await flushPromises();
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    expect(wrapper.find('.password-login').exists()).toBe(true);
    expect(wrapper.text()).toContain('用户名');
    expect(wrapper.text()).toContain('飞书扫码登录暂时失败');
    expect(mocks.start).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('restores the form if cleaning the callback URL fails', async () => {
    mocks.route.query = { feishu: 'complete' };
    mocks.replace.mockRejectedValueOnce(new Error('synthetic navigation failure'));
    const wrapper = mount(LoginView);
    await flushPromises();
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    expect(wrapper.find('.password-login').exists()).toBe(true);
    expect(mocks.complete).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('does not redirect after the callback screen has been left', async () => {
    const completion = deferred();
    mocks.route.query = { feishu: 'complete' };
    mocks.complete.mockReturnValue(completion.promise);
    const wrapper = mount(LoginView);
    await flushPromises();
    wrapper.unmount();
    completion.resolve({ success: true });
    await flushPromises();
    expect(mocks.replace).toHaveBeenCalledTimes(1);
    expect(mocks.config).not.toHaveBeenCalled();
  });

  it('keeps password login available when QR login is disabled and reports an unbound callback', async () => {
    mocks.route.query = { feishu_error: 'unbound' };
    const wrapper = mount(LoginView, { global: { stubs: { 'el-form': true, 'el-form-item': true, 'el-input': true, 'el-button': true, 'el-alert': true } } });
    await flushPromises();
    expect(wrapper.text()).toContain('此飞书账号尚未绑定系统账号');
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

  it('hides credentials as the QR SDK starts redirecting and restores them if navigation fails', async () => {
    mocks.config.mockResolvedValue({ success: true, data: { enabled: true } });
    mocks.start.mockResolvedValue({ success: true, data: { authorize_url: 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=synthetic-client&redirect_uri=https%3A%2F%2Fapp.example%2Flogin&response_type=code&state=synthetic-state' } });
    const wrapper = mount(LoginView);
    await flushPromises();
    expect(wrapper.find('.password-login').exists()).toBe(true);
    const qr = mocks.qrMount.mock.calls[0][0];
    await qr.onRedirect();
    await flushPromises();
    expect(wrapper.find('.password-login').exists()).toBe(false);
    expect(wrapper.find('[role="status"]').exists()).toBe(true);
    expect(mocks.complete).not.toHaveBeenCalled();
    qr.onError('config_unavailable');
    await flushPromises();
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    expect(wrapper.find('.password-login').exists()).toBe(true);
    wrapper.unmount();
  });

  it.each(['sales', 'advertising'])('returns the Feishu QR callback to the complete %s chart detail URL', async (dataset) => {
    const path = `/reports/basic?tab=analysis&feishu_dataset=${dataset}&date_from=2026-10-16&date_to=2026-10-17&store_id=1234567890123456789&region=GB&currency=GBP`;
    vi.stubGlobal('requestAnimationFrame', (callback) => callback());
    mocks.route.query = { redirect: path };
    mocks.config.mockResolvedValue({ success: true, data: { enabled: true } });
    mocks.start.mockResolvedValue({ success: true, data: { authorize_url: 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=synthetic-client&redirect_uri=https%3A%2F%2Fapp.example%2Flogin&response_type=code&state=synthetic-state' } });
    const startView = mount(LoginView);
    await flushPromises();
    await mocks.qrMount.mock.calls[0][0].onRedirect();
    startView.unmount();

    mocks.route.query = { feishu: 'complete' };
    mocks.complete.mockResolvedValue({ success: true });
    mount(LoginView);
    await flushPromises();
    expect(mocks.replace).toHaveBeenLastCalledWith(path);
    vi.unstubAllGlobals();
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
