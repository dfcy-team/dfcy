import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ElMessage, ElMessageBox } from 'element-plus';
import { inject, nextTick, provide, toRef } from 'vue';

const authContext = vi.hoisted(() => ({ allowed: true, manage: true }));
const browserBridge = vi.hoisted(() => ({ navigateTikTokBridge: vi.fn() }));
const adsBridge = vi.hoisted(() => ({ navigateAdsBridge: vi.fn() }));
const adsApi = vi.hoisted(() => ({ startAdsOAuth: vi.fn() }));
vi.mock('../src/api/tiktokAds', () => adsApi);
vi.mock('../src/utils/tiktokAdsBridge', () => adsBridge);
vi.mock('../src/utils/tiktokBrowserBridge', () => browserBridge);
const api = vi.hoisted(() => ({
  bindWarehouseAuthorization: vi.fn(),
  authorizeJifengWarehouse: vi.fn(),
  discoverJifengWarehouses: vi.fn(),
  refreshJifengWarehouse: vi.fn(),
  checkJifengWarehouse: vi.fn(),
  checkIntegrationReadonlyConnection: vi.fn(),
  completeSyntheticStoreAuthorization: vi.fn(),
  completeManualStoreCallback: vi.fn(),
  createSyncJob: vi.fn(),
  fetchStoreAuthorizations: vi.fn(),
  fetchSubjectApiAccess: vi.fn(),
  fetchWarehouseAuthorizations: vi.fn(),
  refreshStoreAuthorization: vi.fn(),
  rebindWarehouseAuthorization: vi.fn(),
  revokeWarehouseAuthorization: vi.fn(),
  revokeStoreAuthorization: vi.fn(),
  startStoreAuthorization: vi.fn(),
}));

vi.mock('../src/api/integrations', () => api);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (permission) => permission === 'integrations.manage'
      ? authContext.manage
      : authContext.allowed,
  }),
}));
vi.mock('../src/utils/actionAccess', () => ({
  getActionAccess: (auth, { permission }) => {
    const allowed = auth.hasPermission(permission);
    return {
      allowed,
      visible: true,
      disabled: !allowed,
      reason: allowed ? '' : `缺少权限：${permission}`,
    };
  },
}));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import SubjectApiAccessDialog from '../src/components/SubjectApiAccessDialog.vue';
import { mockSubjectApiAccess, mockStoreAuthorizations, mockWarehouseAuthorizations } from '../src/mock/integrations';

const TABLE_ROWS = Symbol('subject-api-table-rows');
const stubs = {
  'el-dialog': {
    props: { modelValue: Boolean, title: String },
    emits: ['opened'],
    mounted() {
      if (this.modelValue) this.$emit('opened');
    },
    template: '<div class="dialog"><slot name="header" /><slot /><slot name="footer" /></div>',
  },
  'el-alert': { props: { title: String }, template: '<div class="alert">{{ title }}<slot /></div>' },
  'el-skeleton': { template: '<div class="skeleton" />' },
  'el-tag': { props: { type: String }, template: '<span class="tag"><slot /></span>' },
  'el-button': {
    props: { disabled: Boolean, loading: Boolean, title: String, type: String },
    emits: ['click'],
    template: '<button :disabled="disabled" :title="title" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<label><slot /></label>' },
  'el-select': {
    props: { modelValue: [String, Number], disabled: Boolean },
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  },
  'el-option': {
    props: { label: String, value: [String, Number] },
    template: '<option :value="value">{{ label }}</option>',
  },
  'el-input': {
    props: { modelValue: String, readonly: Boolean },
    template: '<input :value="modelValue" :readonly="readonly" />',
  },
  'el-table': {
    props: { data: { type: Array, default: () => [] } },
    setup(props) {
      provide(TABLE_ROWS, toRef(props, 'data'));
    },
    template: '<div class="table"><slot /></div>',
  },
  'el-table-column': {
    props: { label: String },
    setup() {
      return { rows: inject(TABLE_ROWS, toRef({ data: [] }, 'data')) };
    },
    template: '<div class="table-column" :data-label="label"><div v-for="row in rows" :key="row.id"><slot :row="row" /></div></div>',
  },
  'el-descriptions': { template: '<dl><slot /></dl>' },
  'el-descriptions-item': { props: { label: String }, template: '<div class="description"><dt>{{ label }}</dt><dd><slot /></dd></div>' },
};

function configureApi(subjectType = 'store') {
  const response = mockSubjectApiAccess(subjectType, 1);
  api.fetchSubjectApiAccess.mockResolvedValue(response);
  api.fetchStoreAuthorizations.mockResolvedValue(mockStoreAuthorizations({ store_id: 1 }));
  api.fetchWarehouseAuthorizations.mockResolvedValue(mockWarehouseAuthorizations({ warehouse_id: 1 }));
  api.createSyncJob.mockResolvedValue({ success: true, code: 'OK', data: { id: 999 } });
  api.startStoreAuthorization.mockResolvedValue({ success: true, data: { simulation_callback: { state: 'synthetic' } } });
  api.completeSyntheticStoreAuthorization.mockResolvedValue({ success: true, data: { simulation: true } });
  return response.data.subject;
}

async function mountDialog(subjectType = 'store') {
  const subject = configureApi(subjectType);
  const wrapper = mount(SubjectApiAccessDialog, {
    props: {
      modelValue: true,
      subjectType,
      row: subject,
    },
    global: { stubs },
  });
  await flushPromises();
  await nextTick();
  return wrapper;
}

describe('TikTok Ads configuration selection', () => {
  beforeEach(() => { vi.clearAllMocks(); authContext.allowed = true; authContext.manage = true; });
  it('renders only ready Ads configs and defaults the sole verified config, never Shop', async () => {
    const wrapper = await mountDialog('store');
    const config = { id: 8, platform: 'tiktok', api_type: 'advertising', account_alias: '独立广告配置',
      status: 'verified', environment: 'production', oauth_ready: true, ads_oauth_ready: true };
    wrapper.vm.access.subject.platform = 'tiktok';
    wrapper.vm.access.api_types = ['advertising'];
    wrapper.vm.access.configs = [config, { ...config, id: 9, api_type: 'marketplace', account_alias: '商城配置' },
      { ...config, id: 10, ads_oauth_ready: false, account_alias: '未就绪广告配置' }];
    await nextTick();
    expect(wrapper.vm.adsReadyConfigs.map(c => c.id)).toEqual([8]);
    expect(wrapper.vm.adsConfigId).toBe(8);
    expect(wrapper.findAll('option').map(option => option.text())).toEqual(['独立广告配置']);
    adsApi.startAdsOAuth.mockResolvedValue({ success: true, data: { browser_bridge_url: 'https://dingfengchuangyu.com/saas-tk-ads/start#ticket=fake.signature' } });
    const button = wrapper.findAll('button').find(item => item.text() === '连接广告账户');
    await button.trigger('click'); await flushPromises();
    expect(adsApi.startAdsOAuth).toHaveBeenCalledExactlyOnceWith({ store_id: wrapper.props('row').id, integration_config_id: 8 });
    expect(adsBridge.navigateAdsBridge).toHaveBeenCalledOnce();
    expect(api.startStoreAuthorization).not.toHaveBeenCalled();
    await wrapper.setProps({ modelValue: false }); await nextTick();
    expect(wrapper.vm.adsConfigId).toBeNull();
    await wrapper.setProps({ modelValue: true, row: { ...wrapper.props('row'), id: 9999 } }); await nextTick();
    expect(wrapper.vm.adsConfigId).toBeNull();
    expect(wrapper.vm.adsReadyConfigs).toEqual([]);
    wrapper.unmount();
  });
});

describe('SubjectApiAccessDialog runtime closures', () => {
  async function pendingTikTok() {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = 'tiktok';
    wrapper.vm.access.subject.name = 'TK test shop';
    api.startStoreAuthorization.mockResolvedValue({ success: true, data: {
      authorization_url: 'https://auth.example.test/?state=TEST_PENDING',
      browser_bridge_url: 'https://dingfengchuangyu.com/saas-tk/start#ticket=FAKE_BODY.FAKE_SIGNATURE',
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    } });
    vi.spyOn(window, 'open').mockReturnValue({});
    await wrapper.vm.authorizeStore('marketplace', 'manual-url');
    return wrapper;
  }

  it('puts the TK start action first and uses signed same-tab navigation without a popup', async () => {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = 'tiktok';
    api.startStoreAuthorization.mockResolvedValue({ success: true, data: {
      browser_bridge_url: 'https://dingfengchuangyu.com/saas-tk/start#ticket=FAKE_BODY.FAKE_SIGNATURE',
    } });
    const popup = vi.spyOn(window, 'open').mockReturnValue({});
    await nextTick();
    expect(wrapper.find('.tk-authorization-start').exists()).toBe(true);
    expect(wrapper.vm.tikTokManualFallbackOpen).toBe(false);
    await wrapper.vm.authorizeStore('marketplace');
    expect(browserBridge.navigateTikTokBridge).toHaveBeenCalledExactlyOnceWith('https://dingfengchuangyu.com/saas-tk/start#ticket=FAKE_BODY.FAKE_SIGNATURE');
    expect(popup).not.toHaveBeenCalled();
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('shows an inline TK fallback error instead of stacking warning toasts', async () => {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = 'tiktok';
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/callback?code=FAKE_CODE';
    await wrapper.vm.submitManualCallback('marketplace');
    await wrapper.vm.submitManualCallback('marketplace');
    expect(wrapper.vm.manualCallbackFeedback.marketplace.message).toContain('使用已有回调 URL');
    expect(ElMessage.warning).not.toHaveBeenCalled();
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('prepares the existing-URL entry without navigation even when a browser bridge is available', async () => {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = 'tiktok';
    api.startStoreAuthorization.mockResolvedValue({ success: true, data: {
      authorization_url: 'https://services.tiktokshop.com/open/authorize?service_id=FAKE&state=TEST_PENDING',
      browser_bridge_url: 'https://dingfengchuangyu.com/saas-tk/start#ticket=FAKE_BODY.FAKE_SIGNATURE',
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    } });
    const popup = vi.spyOn(window, 'open').mockReturnValue({});
    await nextTick();
    const manual = wrapper.findAll('button').find((button) => button.text() === '使用已有回调 URL');
    expect(manual).toBeDefined();
    await manual.trigger('click');
    await flushPromises();
    expect(api.startStoreAuthorization).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.tikTokManualFallbackOpen).toBe(true);
    expect(wrapper.vm.pendingTikTokCallbacks.marketplace.state).toBe('TEST_PENDING');
    expect(wrapper.vm.manualCallbackFeedback.marketplace.message).toContain('不会跳转页面');
    expect(popup).not.toHaveBeenCalled();
    expect(browserBridge.navigateTikTokBridge).not.toHaveBeenCalled();
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    wrapper.vm.manualCallbackUrls.marketplace = 'https://dingfengchuangyu.com/callback?app_key=FAKE_APP&code=FAKE_CODE&shop_region=MY';
    api.completeManualStoreCallback.mockResolvedValue({ success: true });
    await wrapper.vm.submitManualCallback('marketplace');
    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1);
    expect(api.completeManualStoreCallback).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      tiktok_pending_token: 'TEST_PENDING', tiktok_manual_confirmed: true,
    }));
    wrapper.unmount();
  });

  it('keeps the automatic route and discards prepared manual state when switching modes', async () => {
    const wrapper = await pendingTikTok();
    wrapper.vm.tikTokManualFallbackOpen = true;
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/callback?code=FAKE_OLD';
    api.startStoreAuthorization.mockResolvedValue({ success: true, data: {
      browser_bridge_url: 'https://dingfengchuangyu.com/saas-tk/start#ticket=FAKE_NEW.FAKE_SIGNATURE',
    } });
    await wrapper.vm.authorizeStore('marketplace');
    expect(browserBridge.navigateTikTokBridge).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('FAKE_NEW'));
    expect(wrapper.vm.tikTokManualFallbackOpen).toBe(false);
    expect(wrapper.vm.pendingTikTokCallbacks.marketplace).toBeUndefined();
    expect(wrapper.vm.manualCallbackUrls.marketplace).toBeUndefined();
    wrapper.unmount();
  });

  it.each(['shopee', 'lazada'])('does not expose or start the TK manual mode for %s', async (platform) => {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = platform;
    await nextTick();
    expect(wrapper.text()).not.toContain('使用已有回调 URL');
    await wrapper.vm.authorizeStore('marketplace', 'manual-url');
    expect(api.startStoreAuthorization).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('rejects missing-state manual preparation without a live session response', async () => {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = 'tiktok';
    api.startStoreAuthorization.mockResolvedValue({ success: true, data: {
      authorization_url: 'https://services.tiktokshop.com/open/authorize?service_id=FAKE',
      expires_at: new Date(Date.now() - 1000).toISOString(),
    } });
    await wrapper.vm.authorizeStore('marketplace', 'manual-url');
    expect(wrapper.vm.tikTokManualFallbackOpen).toBe(false);
    expect(wrapper.vm.pendingTikTokCallbacks.marketplace).toBeUndefined();
    expect(browserBridge.navigateTikTokBridge).not.toHaveBeenCalled();
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each(['closed', 'changed-store'])('discards a delayed existing-URL preparation after %s', async (condition) => {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = 'tiktok';
    let resolveStart;
    api.startStoreAuthorization.mockReturnValue(new Promise((resolve) => { resolveStart = resolve; }));
    const pending = wrapper.vm.authorizeStore('marketplace', 'manual-url');
    await flushPromises();
    if (condition === 'closed') await wrapper.setProps({ modelValue: false });
    else await wrapper.setProps({ row: { ...wrapper.props('row'), id: 99 } });
    resolveStart({ success: true, data: {
      authorization_url: 'https://auth.example.test/?state=FAKE_LATE',
      expires_at: new Date(Date.now() + 300000).toISOString(),
    } });
    await pending;
    expect(wrapper.vm.tikTokManualFallbackOpen).toBe(false);
    expect(wrapper.vm.pendingTikTokCallbacks.marketplace).toBeUndefined();
    expect(browserBridge.navigateTikTokBridge).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('recovers a missing-state TikTok callback only with the in-memory pending session and confirmation', async () => {
    const wrapper = await pendingTikTok();
    api.completeManualStoreCallback.mockResolvedValue({ success: true });
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/callback?app_key=FAKE_APP&code=FAKE_CODE&shop_region=MY';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('TK test shop'), '确认 TikTok 店铺授权', expect.any(Object));
    expect(api.completeManualStoreCallback).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      store_id: 1, integration_config_id: 1, tiktok_pending_token: 'TEST_PENDING', tiktok_manual_confirmed: true,
    }));
    expect(wrapper.vm.pendingTikTokCallbacks.marketplace).toBeUndefined();
    expect(wrapper.vm.manualCallbackUrls.marketplace).toBe('');
    wrapper.unmount();
  });

  it.each(['empty-state', 'duplicate', 'expired', 'closed', 'changed-config', 'missing-session'])('does not downgrade invalid TikTok callback: %s', async (condition) => {
    const wrapper = await pendingTikTok();
    let url = 'https://example.test/callback?app_key=FAKE_APP&code=FAKE_CODE&shop_region=MY';
    if (condition === 'empty-state') url += '&state=';
    if (condition === 'duplicate') url += '&code=FAKE_OTHER';
    if (condition === 'expired') wrapper.vm.pendingTikTokCallbacks.marketplace.expiresAt = Date.now() - 1;
    if (condition === 'closed') wrapper.vm.clearManualCallbacks();
    if (condition === 'changed-config') { wrapper.vm.selections.marketplace = 999; await nextTick(); }
    if (condition === 'missing-session') delete wrapper.vm.pendingTikTokCallbacks.marketplace;
    wrapper.vm.manualCallbackUrls.marketplace = url;
    await wrapper.vm.submitManualCallback('marketplace');
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('cancels TikTok recovery without a request and prevents double submissions', async () => {
    const wrapper = await pendingTikTok();
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/?code=FAKE_CODE';
    ElMessageBox.confirm.mockRejectedValueOnce('cancel');
    await Promise.all([wrapper.vm.submitManualCallback('marketplace'), wrapper.vm.submitManualCallback('marketplace')]);
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    expect(wrapper.vm.pendingTikTokCallbacks.marketplace).toBeUndefined();
    expect(wrapper.vm.busy).toBe('');
    wrapper.unmount();
  });

  it('preserves the ordinary state-bearing TikTok request without fallback fields', async () => {
    const wrapper = await pendingTikTok();
    api.completeManualStoreCallback.mockResolvedValue({ success: true });
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/?state=TEST_PENDING&code=FAKE_CODE';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(api.completeManualStoreCallback).toHaveBeenCalledExactlyOnceWith({
      callback_url: 'https://example.test/?state=TEST_PENDING&code=FAKE_CODE', store_id: 1, integration_config_id: 1,
    });
    wrapper.unmount();
  });

  it('keeps Shopee missing-state callbacks rejected without confirmation', async () => {
    const wrapper = await mountDialog('store');
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/?code=FAKE_CODE';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    expect(ElMessageBox.confirm).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each(['closed', 'changed-store', 'unmounted'])('does not restore a late TikTok start response after %s', async (condition) => {
    const wrapper = await mountDialog('store');
    wrapper.vm.access.subject.platform = 'tiktok';
    let resolveStart;
    api.startStoreAuthorization.mockReturnValue(new Promise((resolve) => { resolveStart = resolve; }));
    const open = vi.spyOn(window, 'open').mockReturnValue({});
    const pending = wrapper.vm.authorizeStore('marketplace');
    await flushPromises();
    if (condition === 'closed') await wrapper.setProps({ modelValue: false });
    if (condition === 'changed-store') await wrapper.setProps({ row: { ...wrapper.props('row'), id: 99 } });
    if (condition === 'unmounted') wrapper.unmount();
    resolveStart({ success: true, data: { authorization_url: 'https://auth.example.test/?state=FAKE_LATE',
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString() } });
    await pending;
    expect(open).not.toHaveBeenCalled();
    if (condition !== 'unmounted') {
      expect(wrapper.vm.pendingTikTokCallbacks.marketplace).toBeUndefined();
      wrapper.unmount();
    }
  });

  it('revalidates a saved token without claiming a new rotation or automatic task recovery', async () => {
    const wrapper = await mountDialog('store');
    const binding = { id: 101, last_error_code: 'AUTO_REFRESH_VALIDATION_FAILED' };
    api.refreshStoreAuthorization.mockResolvedValue({ success: true, data: { id: 101, last_error_code: '' } });
    await wrapper.vm.refreshStoreBinding(binding);
    expect(api.refreshStoreAuthorization).toHaveBeenCalledWith(101, { confirmed: true });
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('不执行只读检查'), '确认刷新令牌', expect.any(Object));
    expect(ElMessage.success).toHaveBeenCalledWith(expect.stringContaining('未执行只读检查'));
  });

  it('does not report validation success when the saved token remains pending', async () => {
    const wrapper = await mountDialog('store');
    const binding = { id: 101, last_error_code: 'AUTO_REFRESH_VALIDATION_PENDING' };
    api.refreshStoreAuthorization.mockResolvedValue({ success: true, data: binding });
    await wrapper.vm.refreshStoreBinding(binding);
    expect(ElMessage.success).not.toHaveBeenCalled();
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('能力矩阵'));
  });

  it('submits a callback for the current store and clears the sensitive input', async () => {
    const wrapper = await mountDialog('store');
    api.completeManualStoreCallback.mockResolvedValue({ success: true });
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/callback?state=FAKE_STATE&code=FAKE_CODE';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(api.completeManualStoreCallback).toHaveBeenCalledWith(expect.objectContaining({ store_id: 1, integration_config_id: 1 }));
    expect(wrapper.vm.manualCallbackUrls.marketplace).toBe('');
    expect(wrapper.emitted('changed')).toBeTruthy();
  });

  it('shows a consumed callback as a conflict, never as new authorization success', async () => {
    const wrapper = await mountDialog('store');
    api.completeManualStoreCallback.mockResolvedValue({ success: false, code: 'STATE_CONFLICT',
      data: { reason_code: 'OAUTH_STATE_CONSUMED' } });
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/callback?state=FAKE_STATE&code=FAKE_CODE';
    await wrapper.vm.submitManualCallback('marketplace');
    await nextTick();
    expect(wrapper.text()).toContain('本次回调已使用');
    expect(ElMessage.success).not.toHaveBeenCalled();
    expect(api.completeManualStoreCallback).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.manualCallbackUrls.marketplace).toBe('');
  });

  it('explains manual processing in the current backend', async () => {
    const wrapper = await mountDialog('store');
    expect(wrapper.text()).toContain('当前页面连接的后端');
    expect(wrapper.text()).toContain('不会访问粘贴地址');
    expect(wrapper.text()).not.toContain('加密写入并绑定 SaaS MySQL');
  });

  it('rejects duplicate callback parameters before submitting', async () => {
    const wrapper = await mountDialog('store');
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/callback?state=ONE&state=TWO&code=TEST';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
  });

  it('rejects invalid callback input without sending it', async () => {
    const wrapper = await mountDialog('store');
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/start';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    expect(ElMessage.warning).toHaveBeenCalled();
  });

  it.each([
    ['OAUTH_STATE_EXPIRED', '授权会话已过期'],
    ['OAUTH_AUTH_REJECTED', '不是本系统登录过期'],
    ['OAUTH_DATABASE_FAILURE', '保存失败'],
  ])('keeps a safe persistent message for %s', async (reason, text) => {
    const wrapper = await mountDialog('store');
    api.completeManualStoreCallback.mockResolvedValue({ success: false, message: 'TEST_SECRET_NOT_FOR_DISPLAY',
      data: { reason_code: reason } });
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/?state=TEST&code=TEST';
    await wrapper.vm.submitManualCallback('marketplace');
    await nextTick();
    expect(wrapper.text()).toContain(text);
    expect(wrapper.text()).not.toContain('TEST_SECRET_NOT_FOR_DISPLAY');
    expect(ElMessage.success).not.toHaveBeenCalled();
    expect(wrapper.vm.busy).toBe('');
  });

  it.each([
    ['exchange_token', 'timeout_uncertain', '结果尚不能确认'],
    ['exchange_token', 'ip_allowlist_rejected', 'Shopee 开发者后台'],
    ['read_developer_secret', 'custody_authentication_rejected', '本地托管服务认证失败'],
    ['save_authorization', 'database_failure', 'Token 已取得'],
  ])('shows safe stage diagnostics for %s', async (stage, category, expected) => {
    const wrapper = await mountDialog('store');
    api.completeManualStoreCallback.mockResolvedValue({ success: false, message: 'FAKE_SECRET',
      data: { reason_code: 'OAUTH_PROVIDER_UNAVAILABLE', diagnostic: {
        diagnostic_id: '0123456789abcdef0123456789abcdef', platform: 'shopee', stage, category,
        platform_error_code: 'UNCLASSIFIED',
      } } });
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/?state=TEST&code=TEST';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(wrapper.text()).toContain(expected);
    expect(wrapper.text()).toContain('0123456789abcdef0123456789abcdef');
    expect(wrapper.text()).toContain('未分类平台错误');
    expect(wrapper.text()).not.toContain('FAKE_SECRET');
    expect(ElMessage.success).not.toHaveBeenCalled();
  });

  it('does not submit a callback twice while the first request is pending', async () => {
    const wrapper = await mountDialog('store');
    let finish;
    api.completeManualStoreCallback.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/?state=TEST&code=TEST';
    const pending = wrapper.vm.submitManualCallback('marketplace');
    await wrapper.vm.submitManualCallback('marketplace');
    expect(api.completeManualStoreCallback).toHaveBeenCalledTimes(1);
    finish({ success: true });
    await pending;
  });

  it('creates warehouse tasks disabled without running a platform check', async () => {
    const wrapper = await mountDialog('warehouse');
    await wrapper.vm.createInventorySyncJob({ id: 202, integration_config_id: 3 });
    expect(api.createSyncJob).toHaveBeenCalledWith(expect.objectContaining({
      warehouse_authorization_id: 202, is_enabled: false, schedule_type: 'manual',
    }));
    expect(api.checkJifengWarehouse).not.toHaveBeenCalled();
  });

  it('clears failed callback input and does not echo server details', async () => {
    const wrapper = await mountDialog('store');
    api.completeManualStoreCallback.mockRejectedValue(new Error('FAKE_SECRET_MUST_NOT_DISPLAY'));
    wrapper.vm.manualCallbackUrls.marketplace = 'https://example.test/callback?state=FAKE_STATE&code=FAKE_CODE';
    await wrapper.vm.submitManualCallback('marketplace');
    expect(wrapper.vm.manualCallbackUrls.marketplace).toBe('');
    expect(ElMessage.error).toHaveBeenCalled();
    expect(String(ElMessage.error.mock.calls)).not.toContain('FAKE_SECRET_MUST_NOT_DISPLAY');
  });
  beforeEach(() => {
    authContext.allowed = true;
    authContext.manage = true;
    vi.clearAllMocks();
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(true);
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'info').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined);
  });

  it('binds the manage permission to the rendered store sync button', async () => {
    authContext.allowed = true;
    authContext.manage = false;
    const wrapper = await mountDialog('store');
    const button = wrapper.findAll('button').find((item) => item.text().includes('创建同步任务'));
    expect(button.exists()).toBe(true);
    expect(button.attributes('disabled')).toBeDefined();
    await button.trigger('click');
    expect(api.createSyncJob).not.toHaveBeenCalled();
  });

  it('uses the selected registered resource in the sync-job payload', async () => {
    const wrapper = await mountDialog('store');
    const selector = wrapper.find('select.store-sync-resource-select');
    expect(selector.exists()).toBe(true);
    await selector.setValue('refund_return');
    const button = wrapper.findAll('button').find((item) => item.text().includes('创建同步任务'));
    await button.trigger('click');
    await flushPromises();
    expect(api.createSyncJob).toHaveBeenCalledWith(expect.objectContaining({
      integration_config_id: 1,
      store_authorization_id: 201,
      resource_type: 'refund_return',
      schedule_type: 'manual',
      is_enabled: false,
    }));
  });

  it('creates a disabled Shopee advertising job instead of a settlement resource', async () => {
    const subject = configureApi('store');
    const base = mockSubjectApiAccess('store', 1).data;
    const marketplaceBinding = base.bindings.find((binding) => binding.status === 'active');
    api.fetchSubjectApiAccess.mockResolvedValue({
      success: true,
      code: 'OK',
      data: {
        ...base,
        api_types: ['advertising'],
        bindings: [{ ...marketplaceBinding, id: 701, api_type: 'advertising' }],
      },
    });
    const wrapper = mount(SubjectApiAccessDialog, {
      props: { modelValue: true, subjectType: 'store', row: subject },
      global: { stubs },
    });
    await flushPromises();
    await nextTick();

    const button = wrapper.findAll('button').find((item) => item.text() === '创建同步任务');
    expect(button.exists()).toBe(true);
    expect(button.attributes('disabled')).toBeUndefined();
    expect(button.attributes('title')).toContain('Shopee 广告数据');
    await button.trigger('click');
    await flushPromises();
    expect(api.createSyncJob).toHaveBeenCalledWith(expect.objectContaining({
      store_authorization_id: 701, resource_type: 'advertising_report',
      schedule_type: 'manual', is_enabled: false,
    }));
    expect(api.createSyncJob.mock.calls.some(([payload]) => payload?.resource_type === 'settlement_bill')).toBe(false);
  });

  it.each(['mapped', 'verified'])('renders %s TikTok Ads mappings without mislabeling or Marketplace actions', async (mappingState) => {
    const subject = configureApi('store');
    const base = mockSubjectApiAccess('store', 1).data;
    const adsMappings = Array.from({ length: 41 }, (_, index) => ({
      mapping_id: index + 1,
      binding_kind: 'tiktok_ads_mapping',
      advertiser_id: String(700000000 + index),
      store_id: 1,
      store_code: 'TK1PH',
      store_name: 'TikTok Philippines',
      integration_config_id: 71,
      account_alias: 'TikTok Ads PH',
      currency: 'PHP',
      timezone: 'Asia/Manila',
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-02T00:00:00Z',
      sync_enabled: false,
      mapping_enabled: false,
      network_enabled: true,
      read_enabled: true,
      credential_configured: index >= 34,
      state: mappingState,
    }));
    api.fetchSubjectApiAccess.mockResolvedValue({
      success: true,
      code: 'OK',
      data: {
        ...base,
        subject: { ...base.subject, platform: 'tiktok' },
        api_types: ['advertising'],
        configs: [{ id: 71, api_type: 'advertising', account_alias: 'TikTok Ads PH', status: 'verified', oauth_ready: true }],
        bindings: [],
        ads_mappings: adsMappings,
      },
    });
    api.fetchStoreAuthorizations.mockResolvedValue({ success: true, data: { results: [] } });

    const wrapper = mount(SubjectApiAccessDialog, {
      props: { modelValue: true, subjectType: 'store', row: subject },
      global: { stubs },
    });
    await flushPromises();
    await nextTick();

    expect(wrapper.findAll('.tiktok-ads-mapping')).toHaveLength(41);
    expect(wrapper.find('.ads-mapping-summary').text()).toContain(`41 个广告户已绑定，${mappingState === 'verified' ? 0 : 41} 个待校验`);
    expect(wrapper.find('.ads-mapping-summary').text()).toContain('41 个读取开关未开启');
    expect(wrapper.find('.tiktok-ads-mapping').text()).toContain(mappingState === 'verified' ? '账户已验证' : '已绑定 · 待校验');
    expect(wrapper.find('.tiktok-ads-mapping').text()).toContain('读取开关未开启');
    expect(wrapper.find('.tiktok-ads-mapping').text()).toContain('映射创建时间');
    expect(wrapper.find('.tiktok-ads-mapping').text()).not.toContain('令牌到期时间');
    expect(wrapper.find('.tiktok-ads-mapping').findAll('button')).toHaveLength(0);
    expect(wrapper.findAll('button').some(item => /授权 TikTok 广告账户/.test(item.text()))).toBe(false);

    await wrapper.vm.authorizeStore('advertising');
    await wrapper.vm.submitManualCallback('advertising');
    expect(api.startStoreAuthorization).not.toHaveBeenCalled();
    expect(api.completeManualStoreCallback).not.toHaveBeenCalled();
    expect(api.refreshStoreAuthorization).not.toHaveBeenCalled();
    expect(api.revokeStoreAuthorization).not.toHaveBeenCalled();
    expect(api.createSyncJob).not.toHaveBeenCalled();
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('独立广告授权导入流程'));
  });

  it('hides legacy TikTok Ads Marketplace bindings and blocks direct refresh or revoke calls', async () => {
    const subject = configureApi('store');
    const base = mockSubjectApiAccess('store', 1).data;
    const mapping = {
      mapping_id: 82,
      binding_kind: 'tiktok_ads_mapping',
      advertiser_id: '700000082',
      store_id: 1,
      store_code: 'TK1PH',
      store_name: 'TikTok Philippines',
      integration_config_id: 71,
      account_alias: 'TikTok Ads PH',
      currency: 'PHP',
      timezone: 'Asia/Manila',
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-02T00:00:00Z',
      sync_enabled: false,
      mapping_enabled: false,
      network_enabled: true,
      read_enabled: true,
      credential_configured: true,
      state: 'mapped',
    };
    const legacyBinding = {
      id: 4001,
      api_type: 'advertising',
      platform: 'tiktok',
      status: 'active',
      integration_config_id: 71,
      platform_store_id: mapping.advertiser_id,
      account_alias: 'Legacy TikTok Ads MSA row',
    };
    api.fetchSubjectApiAccess.mockResolvedValue({
      success: true,
      code: 'OK',
      data: {
        ...base,
        subject: { ...base.subject, platform: 'tiktok' },
        api_types: ['advertising'],
        configs: [{ id: 71, api_type: 'advertising', account_alias: 'TikTok Ads PH', status: 'verified', oauth_ready: true }],
        bindings: [legacyBinding],
        ads_mappings: [mapping],
      },
    });
    api.fetchStoreAuthorizations.mockResolvedValue({ success: true, data: { results: [] } });

    const wrapper = mount(SubjectApiAccessDialog, {
      props: { modelValue: true, subjectType: 'store', row: subject },
      global: { stubs },
    });
    await flushPromises();
    await nextTick();

    expect(wrapper.findAll('.tiktok-ads-mapping')).toHaveLength(1);
    expect(wrapper.vm.activeBindings('advertising')).toEqual([]);
    expect(wrapper.vm.allBindings('advertising')).toEqual([]);
    expect(wrapper.text()).not.toContain('Legacy TikTok Ads MSA row');
    expect(wrapper.findAll('button').some((button) => /刷新令牌|撤销广告户授权|撤销授权|创建同步任务|授权详情/.test(button.text()))).toBe(false);

    await wrapper.vm.refreshStoreBinding(legacyBinding);
    await wrapper.vm.disableStoreBinding(legacyBinding);
    await wrapper.vm.refreshStoreBinding(mapping);
    await wrapper.vm.disableStoreBinding(mapping);

    expect(api.refreshStoreAuthorization).not.toHaveBeenCalled();
    expect(api.revokeStoreAuthorization).not.toHaveBeenCalled();
    expect(ElMessageBox.confirm).not.toHaveBeenCalled();
  });

  it('preserves Marketplace renewal metadata while merging history and shows live gate blockers', async () => {
    const subject = configureApi('store');
    const base = mockSubjectApiAccess('store', 1).data;
    const binding = base.bindings.find((row) => row.status === 'active');
    Object.assign(binding, {
      renewal_owner: 'saas',
      renewal: {
        enabled: true,
        state: 'blocked',
        renewal_mode: 'per-binding',
        configuration_ready: false,
        configuration_blockers: ['CALLBACK_NOT_APPROVED'],
        expires_at: '2026-10-10T00:00:00Z',
        next_refresh_due_at: '2026-10-09T00:00:00Z',
        last_refreshed_at: '2026-10-01T00:00:00Z',
        failure_category: 'configuration_blocked',
        scheduler_metadata: { heartbeat_state: 'recent', queue: 'credential-refresh' },
      },
    });
    base.renewal_scheduler = { heartbeat_state: 'recent', queue: 'credential-refresh-fallback' };
    api.fetchSubjectApiAccess.mockResolvedValue({ success: true, data: base });
    api.fetchStoreAuthorizations.mockResolvedValue({
      success: true,
      data: { results: [{ id: binding.id, status: 'active', renewal: null, renewal_owner: null }] },
    });

    const wrapper = mount(SubjectApiAccessDialog, {
      props: { modelValue: true, subjectType: 'store', row: subject },
      global: { stubs },
    });
    await flushPromises();
    await nextTick();
    const merged = wrapper.vm.access.bindings.find((row) => row.id === binding.id);
    expect(merged.renewal).toMatchObject({
      state: 'blocked',
      configuration_ready: false,
      configuration_blockers: ['CALLBACK_NOT_APPROVED'],
      next_refresh_due_at: '2026-10-09T00:00:00Z',
      scheduler_metadata: { heartbeat_state: 'recent', queue: 'credential-refresh' },
    });
    expect(merged.renewal_owner).toBe('saas');
    expect(wrapper.text()).toContain('续期状态');
    expect(wrapper.text()).toContain('配置未就绪');
    expect(wrapper.text()).toContain('CALLBACK_NOT_APPROVED');
    expect(wrapper.text()).toContain('credential-refresh');
    const saasBindingWithoutInlineScheduler = {
      ...merged,
      renewal: { ...merged.renewal, scheduler_metadata: undefined },
    };
    expect(wrapper.vm.schedulerMetadataLabel(saasBindingWithoutInlineScheduler)).toContain('credential-refresh-fallback');
  });

  it('does not apply the SaaS scheduler fallback to an external TikTok renewal binding', async () => {
    const subject = configureApi('store');
    const base = mockSubjectApiAccess('store', 1).data;
    const binding = base.bindings.find((row) => row.status === 'active');
    Object.assign(binding, {
      platform: 'tiktok',
      renewal_owner: 'external',
      renewal: { enabled: false, state: 'disabled' },
    });
    base.subject = { ...base.subject, platform: 'tiktok' };
    base.renewal_scheduler = { heartbeat_state: 'recent', queue: 'credential-refresh-external' };
    api.fetchSubjectApiAccess.mockResolvedValue({ success: true, data: base });
    api.fetchStoreAuthorizations.mockResolvedValue({
      success: true,
      data: { results: [{ id: binding.id, status: 'active', renewal: null, renewal_owner: null }] },
    });

    const wrapper = mount(SubjectApiAccessDialog, {
      props: { modelValue: true, subjectType: 'store', row: subject },
      global: { stubs },
    });
    await flushPromises();
    await nextTick();

    const merged = wrapper.vm.access.bindings.find((row) => row.id === binding.id);
    expect(merged.renewal_owner).toBe('external');
    expect(wrapper.vm.renewalOwnerLabel(merged)).toBe('外部维护');
    expect(wrapper.vm.schedulerMetadataLabel(merged)).toBe('');
    expect(wrapper.text()).not.toContain('credential-refresh-external');
  });

  it('renders a validated URL and keeps a manual copy action when popup and clipboard fail', async () => {
    const wrapper = await mountDialog('store');
    const authorizationUrl = 'https://auth.example.test/oauth/authorize?state=runtime';
    api.startStoreAuthorization.mockResolvedValue({ success: true, data: { authorization_url: authorizationUrl } });
    vi.spyOn(window, 'open').mockImplementation(() => null);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });

    const authorize = wrapper.findAll('button').find((item) => /授权.*Shopee/.test(item.text()));
    expect(authorize.exists()).toBe(true);
    await authorize.trigger('click');
    await flushPromises();

    const fallback = wrapper.find('.authorization-url-fallback');
    expect(fallback.exists()).toBe(true);
    expect(fallback.find('input').element.value).toBe(authorizationUrl);
    const copy = fallback.findAll('button').find((item) => item.text().includes('复制授权地址'));
    expect(copy.exists()).toBe(true);
    await copy.trigger('click');
    expect(ElMessage.warning).toHaveBeenCalledWith('复制失败，请手动选择并复制授权地址。');
  });

  it('loads history and opens the masked authorization detail from a rendered row', async () => {
    const wrapper = await mountDialog('store');
    const historyDetail = wrapper.findAll('button').find((item) => item.text() === '查看详情');
    expect(historyDetail.exists()).toBe(true);
    await historyDetail.trigger('click');
    await nextTick();
    expect(wrapper.vm.authorizationDetailOpen).toBe(true);
    expect(wrapper.vm.selectedAuthorizationDetail).toMatchObject({ status: 'expired' });
    expect(wrapper.text()).toContain('access_credential_hint=••••0203');
  });

  it('persists the provider warehouse code when replacing a warehouse binding', async () => {
    api.rebindWarehouseAuthorization.mockResolvedValue({
      success: true,
      code: 'OK',
      data: { authorization: { id: 303 }, idempotent: false, operation: 'warehouse_rebind' },
    });
    const wrapper = await mountDialog('warehouse');
    expect(wrapper.vm.warehouseExternalCode).toBe('MY-JIFENG-01');

    wrapper.vm.warehouseExternalCode = 'MY-JIFENG-02';
    wrapper.vm.warehouseEmail = 'fake@example.test';
    wrapper.vm.warehouseToken = 'test-token';
    api.authorizeJifengWarehouse.mockResolvedValue({ success: true });
    await wrapper.vm.authorizeWarehouse('inventory');
    await flushPromises();

    expect(api.rebindWarehouseAuthorization).toHaveBeenCalledWith(
      202,
      expect.objectContaining({
        warehouse_id: 1,
        integration_config_id: 3,
        external_warehouse_code: 'MY-JIFENG-02',
        replace: true,
        expected_authorization_id: 202,
      }),
    );
  });

  it('saves then authorizes with an optional empty external code', async () => {
    api.rebindWarehouseAuthorization.mockResolvedValue({ success: true, data: { authorization: { id: 303 } } });
    api.authorizeJifengWarehouse.mockResolvedValue({ success: true });
    const wrapper = await mountDialog('warehouse');
    wrapper.vm.warehouseExternalCode = '';
    wrapper.vm.warehouseEmail = 'fake@example.test';
    wrapper.vm.warehouseToken = 'test-token';
    await wrapper.vm.authorizeWarehouse('inventory');
    await flushPromises();
    expect(api.rebindWarehouseAuthorization).toHaveBeenCalledWith(202, expect.objectContaining({
      external_warehouse_code: '', email: 'fake@example.test', token: 'test-token',
    }));
    expect(api.authorizeJifengWarehouse).toHaveBeenCalledExactlyOnceWith(303);
    expect(api.rebindWarehouseAuthorization.mock.invocationCallOrder[0]).toBeLessThan(api.authorizeJifengWarehouse.mock.invocationCallOrder[0]);
    expect(wrapper.text()).not.toContain('保存仓库 API 配置');
    expect(wrapper.findAll('button').filter(button => button.text() === '重新授权')).toHaveLength(1);
    const externalCodeField = wrapper.find('label[label="服务商外部仓库编码（选填）"]');
    expect(externalCodeField.exists()).toBe(true);
    expect(externalCodeField.attributes('required')).toBeUndefined();
  });

  it('keeps a long warehouse authorization history inside a local scroll container', async () => {
    const wrapper = await mountDialog('warehouse');
    expect(wrapper.find('.authorization-history-table').exists()).toBe(true);
    expect(wrapper.findAll('.authorization-history-table .table').length).toBeGreaterThan(0);
  });

  it('keeps saved bindings separate from successful validation', async () => {
    const wrapper = await mountDialog('warehouse');
    const button = wrapper.findAll('button').find(item => item.text().includes('创建库存同步任务'));
    expect(button).toBeDefined();
    expect(button.attributes('disabled')).toBeDefined();
    expect(wrapper.text()).toContain('授权成功后仍需只读校验');
    Object.assign(wrapper.vm.primaryBinding('inventory'), {email: 'fake@example.test', token_configured: true});
    wrapper.vm.warehouseEmail = 'fake@example.test';
    api.authorizeJifengWarehouse.mockResolvedValue({ success: true });
    await wrapper.vm.authorizeWarehouse('inventory');
    expect(ElMessageBox.confirm).toHaveBeenCalled();
    expect(api.authorizeJifengWarehouse).toHaveBeenCalledWith(202);
    expect(api.checkJifengWarehouse).not.toHaveBeenCalled();
    expect(api.createSyncJob).not.toHaveBeenCalled();
    expect(api.rebindWarehouseAuthorization).not.toHaveBeenCalled();
  });

  it('uses one authorization button for a new warehouse and binds before exchanging', async () => {
    const wrapper = await mountDialog('warehouse');
    wrapper.vm.access.bindings = [];
    wrapper.vm.warehouseEmail = 'fake@example.test';
    wrapper.vm.warehouseToken = 'FAKE_TOKEN';
    await nextTick();
    expect(wrapper.findAll('button').filter(button => button.text() === '授权')).toHaveLength(1);
    expect(wrapper.text()).not.toContain('保存仓库 API 配置');
    api.bindWarehouseAuthorization.mockResolvedValue({success: true, data: {authorization: {id: 304}}});
    api.authorizeJifengWarehouse.mockResolvedValue({success: true});
    await wrapper.vm.authorizeWarehouse('inventory');
    expect(api.bindWarehouseAuthorization).toHaveBeenCalledTimes(1);
    expect(api.authorizeJifengWarehouse).toHaveBeenCalledExactlyOnceWith(304);
    expect(api.rebindWarehouseAuthorization).not.toHaveBeenCalled();
  });

  it('stops on save failure without exchanging or showing success', async () => {
    const wrapper = await mountDialog('warehouse');
    wrapper.vm.warehouseEmail = 'fake@example.test';
    wrapper.vm.warehouseToken = 'FAKE_TOKEN';
    api.rebindWarehouseAuthorization.mockResolvedValue({success: false, message: '保存失败'});
    await wrapper.vm.authorizeWarehouse('inventory');
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
    expect(ElMessage.success).not.toHaveBeenCalled();
    expect(wrapper.vm.busy).toBe('');
  });

  it('requires a new token for consumed authorizations and cancellation has no writes', async () => {
    const wrapper = await mountDialog('warehouse');
    wrapper.vm.warehouseEmail = 'fake@example.test';
    Object.assign(wrapper.vm.primaryBinding('inventory'), {token_configured: true, bootstrap_consumed_at: '2026-09-10T00:00:00Z'});
    await wrapper.vm.authorizeWarehouse('inventory');
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('填写新的 Token'));
    expect(api.rebindWarehouseAuthorization).not.toHaveBeenCalled();
    wrapper.vm.warehouseToken = 'NEW_FAKE_TOKEN';
    ElMessageBox.confirm.mockRejectedValueOnce('cancel');
    await wrapper.vm.authorizeWarehouse('inventory');
    expect(api.rebindWarehouseAuthorization).not.toHaveBeenCalled();
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
    expect(wrapper.vm.busy).toBe('');
  });

  it('blocks double clicks and never retries an uncertain exchange', async () => {
    const wrapper = await mountDialog('warehouse');
    wrapper.vm.warehouseEmail = 'fake@example.test';
    wrapper.vm.warehouseToken = 'FAKE_TOKEN';
    api.rebindWarehouseAuthorization.mockResolvedValue({success: true, data: {authorization: {id: 305}}});
    api.authorizeJifengWarehouse.mockRejectedValue(new Error('授权结果未能确认'));
    await Promise.all([wrapper.vm.authorizeWarehouse('inventory'), wrapper.vm.authorizeWarehouse('inventory')]);
    expect(api.rebindWarehouseAuthorization).toHaveBeenCalledTimes(1);
    expect(api.authorizeJifengWarehouse).toHaveBeenCalledExactlyOnceWith(305);
    expect(ElMessage.success).not.toHaveBeenCalled();
    expect(wrapper.vm.busy).toBe('');
  });

  it('navigates warehouse checks to the capability matrix without any API call', async () => {
    const wrapper = await mountDialog('warehouse');
    api.checkJifengWarehouse.mockResolvedValue({ success: true, data: { connected: true } });
    wrapper.vm.openCapabilityMatrix({ id: 202, integration_config_id: 3, status: 'active', has_sync_job: false });
    expect(api.checkJifengWarehouse).not.toHaveBeenCalled();
    expect(api.createSyncJob).not.toHaveBeenCalled();
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
    expect(api.fetchSubjectApiAccess).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]]);
  });

  it('does not invoke a readonly check from the warehouse dialog', async () => {
    const wrapper = await mountDialog('warehouse');
    api.checkJifengWarehouse.mockResolvedValue({ success: false, message: '连接校验失败' });
    wrapper.vm.openCapabilityMatrix({ id: 202, integration_config_id: 3, status: 'active', has_sync_job: false });
    expect(api.checkJifengWarehouse).not.toHaveBeenCalled();
    expect(api.fetchSubjectApiAccess).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted('changed')).toBeUndefined();
    expect(ElMessage.error).not.toHaveBeenCalled();
  });

  it('refreshes the warehouse authorization without using the bootstrap endpoint', async () => {
    const wrapper = await mountDialog('warehouse');
    api.refreshJifengWarehouse.mockResolvedValue({ success: true });
    await wrapper.vm.refreshWarehouseAuthorization({ id: 202 });
    expect(api.refreshJifengWarehouse).toHaveBeenCalledWith(202);
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
    expect(ElMessage.success).toHaveBeenCalledWith(expect.stringContaining('未执行只读检查'));
    expect(api.fetchSubjectApiAccess).toHaveBeenCalledTimes(2);
    expect(wrapper.emitted('changed')).toHaveLength(1);
  });

  it('shows post-authorization discovery failure without repeating the exchange or claiming success', async () => {
    const wrapper = await mountDialog('warehouse');
    Object.assign(wrapper.vm.primaryBinding('inventory'), { email: 'fake@example.test', token_configured: true });
    wrapper.vm.warehouseEmail = 'fake@example.test';
    api.authorizeJifengWarehouse.mockResolvedValue({ success: true, data: { warehouse_discovery: {
      status: 'failed', warehouses: [], message: '现有授权未清除，请重试获取仓库',
    } } });
    await wrapper.vm.authorizeWarehouse('inventory');
    expect(api.authorizeJifengWarehouse).toHaveBeenCalledExactlyOnceWith(202);
    expect(ElMessage.success).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('现有授权未清除');
    expect(api.discoverJifengWarehouses).not.toHaveBeenCalled();
  });

  it('fetches warehouse codes with an existing authorization without saving credentials or exchanging again', async () => {
    const wrapper = await mountDialog('warehouse');
    Object.assign(wrapper.vm.primaryBinding('inventory'), { oauth_token_available: true });
    api.discoverJifengWarehouses.mockResolvedValue({ success: true, data: { warehouse_discovery: {
      status: 'linked', warehouses: [], message: '仓库编号已关联；尚未完成库存只读校验。',
    } } });
    await wrapper.vm.getWarehouseCodes();
    expect(api.discoverJifengWarehouses).toHaveBeenCalledExactlyOnceWith(202, {});
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
    expect(api.rebindWarehouseAuthorization).not.toHaveBeenCalled();
    expect(api.checkJifengWarehouse).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('尚未完成库存只读校验');
  });

  it('requires an explicit warehouse choice and confirmation when several warehouses are returned', async () => {
    const wrapper = await mountDialog('warehouse');
    Object.assign(wrapper.vm.primaryBinding('inventory'), { oauth_token_available: true });
    api.discoverJifengWarehouses.mockResolvedValue({ success: true, data: { warehouse_discovery: {
      status: 'selection_required', message: '请选择仓库', warehouses: [
        { code: 'REMOTE-1', name: 'One', country: 'MY', selectable: true },
        { code: 'REMOTE-2', name: 'Two', country: 'MY', selectable: true },
      ],
    } } });
    await wrapper.vm.getWarehouseCodes();
    expect(wrapper.vm.warehouseChoice).toBe('');
    expect(wrapper.text()).toContain('确认关联仓库');
    expect(api.discoverJifengWarehouses).toHaveBeenCalledTimes(1);
    Object.assign(wrapper.vm.primaryBinding('inventory'), { oauth_token_available: true });
    wrapper.vm.warehouseChoice = 'REMOTE-2';
    ElMessageBox.confirm.mockRejectedValueOnce('cancel');
    await wrapper.vm.getWarehouseCodes(true);
    expect(api.discoverJifengWarehouses).toHaveBeenCalledTimes(1);
    await wrapper.vm.getWarehouseCodes(true);
    expect(api.discoverJifengWarehouses).toHaveBeenLastCalledWith(202, { external_warehouse_code: 'REMOTE-2' });
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
  });

  it('recovers from warehouse discovery network errors and prevents repeated clicks', async () => {
    const wrapper = await mountDialog('warehouse');
    Object.assign(wrapper.vm.primaryBinding('inventory'), { oauth_token_available: true });
    api.discoverJifengWarehouses.mockRejectedValue(new Error('网络超时'));
    await Promise.all([wrapper.vm.getWarehouseCodes(), wrapper.vm.getWarehouseCodes()]);
    expect(api.discoverJifengWarehouses).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.busy).toBe('');
    expect(wrapper.vm.warehouseDiscovery.status).toBe('failed');
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
    authContext.allowed = false;
    const denied = await mountDialog('warehouse');
    await denied.vm.getWarehouseCodes();
    expect(api.discoverJifengWarehouses).toHaveBeenCalledTimes(1);
  });
});
