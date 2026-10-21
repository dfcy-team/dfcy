import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import { mockSubjectApiAccess } from '../src/mock/integrations';

const mocks = vi.hoisted(() => ({ shopStart: vi.fn(), shopComplete: vi.fn(), adsStart: vi.fn(), adsComplete: vi.fn(),
  shopFetch: vi.fn(), adsGet: vi.fn(), access: vi.fn(), push: vi.fn(), authenticated: true, route: {} }));
vi.mock('../src/api/integrations', () => ({
  fetchSubjectApiAccess: mocks.access, fetchStoreAuthorizations: async () => ({ success: true, data: [] }),
  startStoreAuthorization: mocks.shopStart, completeTikTokDirectAuthorization: mocks.shopComplete,
  fetchTikTokShopBinding: mocks.shopFetch,
}));
vi.mock('../src/api/tiktokAds', () => ({ startAdsOAuth: mocks.adsStart, completeAdsDirectOAuth: mocks.adsComplete, getAdsSession: mocks.adsGet }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: mocks.authenticated, hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn() }), useRoute: () => mocks.route }));
const origin = 'https://saas.example.test';
const realWindow = window;
const realNavigator = navigator;
const wrappers = [];
const stubs = {
  ElDialog: { template: '<div><slot name="header"/><slot/></div>' },
  ElButton: { props: ['disabled'], template: '<button :disabled="disabled"><slot/></button>' },
  ElInput: { props: ['modelValue'], template: '<input :value="modelValue" />' },
  ElForm: { template: '<form><slot/></form>' }, ElFormItem: { template: '<div><slot/></div>' },
  ElSelect: { template: '<div><slot/></div>' }, ElOption: true, ElAlert: true, ElTag: true,
  ElSkeleton: true, ElTable: true, ElTableColumn: true, ElDescriptions: true, ElDescriptionsItem: true,
  TikTokAdsSessionPanel: true,
};
function tab(path, search = '') {
  const data = new Map();
  const location = { origin, pathname: path, search, hash: '' };
  const history = { replaceState: vi.fn(() => { location.search = ''; location.hash = ''; }) };
  const storage = { getItem: key => data.get(key) ?? null, setItem: vi.fn((key, value) => data.set(key, value)), removeItem: key => data.delete(key) };
  return { location, history, sessionStorage: storage, data };
}
function selectTab(value) {
  vi.stubGlobal('window', new Proxy(realWindow, { get: (target, key) => key in value ? value[key] : Reflect.get(target, key, target) }));
}
describe('real manual form -> no-opener callback document -> explicit clipboard handoff', () => {
  beforeAll(async () => {
    // Compile the real Vue modules outside the per-flow timeout; each flow still gets fresh module state.
    await import('../src/components/SubjectApiAccessDialog.vue');
    await import('../src/views/integrations/TikTokAuthorizationResult.vue');
    await import('../src/views/integrations/TikTokAdsAuthorizationResult.vue');
  }, 30000);
  beforeEach(() => { vi.clearAllMocks(); mocks.authenticated = true; });
  afterEach(() => {
    wrappers.splice(0).forEach(wrapper => wrapper.unmount());
    vi.unstubAllGlobals();
  });
  it.each(['shop', 'ads'])('%s handoff uses real capture, copy button and originating manual form with no secret persistence', async kind => {
    const path = kind === 'shop' ? '/integrations/tiktok/shop-callback' : '/integrations/tiktok-ads/direct-callback';
    const original = tab('/master-data/stores');
    selectTab(original);
    vi.resetModules();
    const Dialog = (await import('../src/components/SubjectApiAccessDialog.vue')).default;
    const base = mockSubjectApiAccess('store', 1).data;
    const apiType = kind === 'shop' ? 'marketplace' : 'advertising';
    const config = { id: 71, platform: 'tiktok', api_type: apiType, account_alias: 'Demo config', status: 'verified',
      environment: 'production', oauth_ready: true, ads_oauth_ready: true, scopes: [], callback_url: origin + path };
    base.subject.platform = 'tiktok'; base.api_types = [apiType]; base.configs = [config]; base.bindings = [];
    mocks.access.mockResolvedValue({ success: true, data: base });
    const direct = { browser_token: 'DEMO_PROOF', callback_url: origin + path, expires_at: new Date(Date.now() + 60000).toISOString() };
    const authorization_url = kind === 'shop'
      ? 'https://services.tiktokshop.com/open/authorize?service_id=demo&state=demo'
      : 'https://business-api.tiktok.com/portal/auth?app_id=demo&state=demo&redirect_uri=' + encodeURIComponent(origin + path);
    const start = kind === 'shop' ? mocks.shopStart : mocks.adsStart;
    const complete = kind === 'shop' ? mocks.shopComplete : mocks.adsComplete;
    start.mockResolvedValue({ success: true, data: { direct_callback: direct, authorization_url } });
    complete.mockResolvedValue({ success: false, data: { reason_code: 'OAUTH_STATE_CONSUMED' } });
    const form = mount(Dialog, { props: { modelValue: true, subjectType: 'store', row: base.subject }, global: { stubs } });
    wrappers.push(form);
    await form.vm.load(); await flushPromises(); await nextTick();
    if (kind === 'shop') { form.vm.selections.marketplace = 71; await nextTick(); await form.vm.authorizeStore('marketplace', 'manual-url'); }
    else { await nextTick(); await form.vm.connectAds('manual-url'); }
    expect(start).toHaveBeenCalledOnce();
    const key = kind === 'shop' ? 'saas.tiktok.direct-context.v1' : 'saas.tiktok.ads-direct-context.v1';
    expect(original.data.has(key)).toBe(true);

    // A new document has no opener and no sessionStorage clone. Import captures before the view mounts.
    const newTab = tab(path, kind === 'shop' ? '?code=DEMO_CODE&state=demo' : '?auth_code=DEMO_CODE&code=DEMO_CODE&state=demo');
    selectTab(newTab); vi.resetModules(); mocks.authenticated = false;
    mocks.route = { path, query: {} };
    const Result = (await import(kind === 'shop' ? '../src/views/integrations/TikTokAuthorizationResult.vue' : '../src/views/integrations/TikTokAdsAuthorizationResult.vue')).default;
    expect(newTab.location.search).toBe('');
    expect(newTab.history.replaceState).toHaveBeenCalled();
    let copied = '';
    const writeText = vi.fn(async value => { copied = value; });
    vi.stubGlobal('navigator', new Proxy(realNavigator, { get: (target, prop) => prop === 'clipboard' ? { writeText } : Reflect.get(target, prop, target) }));
    const result = mount(Result, { global: { stubs } }); wrappers.push(result); await flushPromises();
    expect(result.text()).not.toContain('DEMO_CODE');
    expect(result.html()).not.toContain('DEMO_CODE');
    expect(complete).not.toHaveBeenCalled();
    expect(mocks.shopFetch).not.toHaveBeenCalled(); expect(mocks.adsGet).not.toHaveBeenCalled();
    expect(writeText).not.toHaveBeenCalled();
    const button = result.findAll('button').find(item => item.text() === '复制回调URL，返回原标签页粘贴');
    expect(button).toBeDefined(); await button.trigger('click'); await flushPromises();
    expect(writeText).toHaveBeenCalledOnce();
    expect(new URL(copied).origin + new URL(copied).pathname).toBe(origin + path);
    expect(new URL(copied).searchParams.get('code')).toBe('DEMO_CODE');
    expect(result.text()).not.toContain('复制回调URL，返回原标签页粘贴');
    expect(newTab.data.size).toBe(0); expect(newTab.sessionStorage.setItem).not.toHaveBeenCalled();
    result.unmount(); wrappers.splice(wrappers.indexOf(result), 1);

    // A reload has no URL parameters and must offer no recovery or exchange.
    vi.resetModules();
    const Reloaded = (await import(kind === 'shop' ? '../src/views/integrations/TikTokAuthorizationResult.vue' : '../src/views/integrations/TikTokAdsAuthorizationResult.vue')).default;
    const refreshed = mount(Reloaded, { global: { stubs } }); wrappers.push(refreshed); await flushPromises();
    expect(refreshed.text()).not.toContain('复制回调URL，返回原标签页粘贴');
    expect(complete).not.toHaveBeenCalled(); refreshed.unmount(); wrappers.splice(wrappers.indexOf(refreshed), 1);

    selectTab(original); mocks.authenticated = true;
    if (kind === 'shop') { form.vm.manualCallbackUrls.marketplace = copied; await form.vm.submitManualCallback('marketplace'); }
    else { form.vm.adsCallbackUrl = copied; await form.vm.submitAdsDirectCallback(); }
    expect(complete).toHaveBeenCalledExactlyOnceWith({ browser_token: 'DEMO_PROOF',
      browser_verifier: start.mock.calls[0][0].tiktok_browser_verifier,
      callback_params: kind === 'shop' ? { code: 'DEMO_CODE', state: 'demo' } : { auth_code: 'DEMO_CODE', code: 'DEMO_CODE', state: 'demo' } });
    expect(original.data.has(key)).toBe(false);
  });
  it.each(['shop', 'ads'])('%s discards an un-copied handoff on unmount', async kind => {
    const path = kind === 'shop' ? '/integrations/tiktok/shop-callback' : '/integrations/tiktok-ads/direct-callback';
    selectTab(tab(path, '?code=DEMO_UNCOPIED&state=demo')); vi.resetModules();
    mocks.authenticated = false; mocks.route = { path, query: {} };
    const Result = (await import(kind === 'shop' ? '../src/views/integrations/TikTokAuthorizationResult.vue' : '../src/views/integrations/TikTokAdsAuthorizationResult.vue')).default;
    const first = mount(Result, { global: { stubs } }); await flushPromises();
    expect(first.text()).toContain('复制回调URL，返回原标签页粘贴');
    first.unmount();
    const second = mount(Result, { global: { stubs } }); wrappers.push(second); await flushPromises();
    expect(second.text()).not.toContain('复制回调URL，返回原标签页粘贴');
    expect(second.html()).not.toContain('DEMO_UNCOPIED');
    expect(mocks.shopComplete).not.toHaveBeenCalled(); expect(mocks.adsComplete).not.toHaveBeenCalled();
  });
});
