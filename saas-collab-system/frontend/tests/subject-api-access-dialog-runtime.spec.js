import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ElMessage, ElMessageBox } from 'element-plus';
import { inject, nextTick, provide, toRef } from 'vue';

const authContext = vi.hoisted(() => ({ allowed: true, manage: true }));
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

describe('SubjectApiAccessDialog runtime closures', () => {
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

  it('disables an active advertising binding and never sends an unsupported resource', async () => {
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
    expect(button.attributes('disabled')).toBeDefined();
    expect(button.attributes('title')).toContain('广告 API 尚未注册');
    await button.trigger('click');
    await flushPromises();
    expect(api.createSyncJob).not.toHaveBeenCalled();
    expect(api.createSyncJob.mock.calls.some(([payload]) => payload?.resource_type === 'settlement_bill')).toBe(false);
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
    wrapper.vm.warehouseToken = 'FAKE_TOKEN';
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

  it('allows readonly validation before a sync job exists', async () => {
    const wrapper = await mountDialog('warehouse');
    api.checkJifengWarehouse.mockResolvedValue({ success: true, data: { connected: true } });
    await wrapper.vm.checkToken({ id: 202, integration_config_id: 3, status: 'active', has_sync_job: false });
    expect(api.checkJifengWarehouse).toHaveBeenCalledWith(202);
    expect(api.createSyncJob).not.toHaveBeenCalled();
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
  });

  it('refreshes the warehouse authorization without using the bootstrap endpoint', async () => {
    const wrapper = await mountDialog('warehouse');
    api.refreshJifengWarehouse.mockResolvedValue({ success: true });
    await wrapper.vm.refreshWarehouseAuthorization({ id: 202 });
    expect(api.refreshJifengWarehouse).toHaveBeenCalledWith(202);
    expect(api.authorizeJifengWarehouse).not.toHaveBeenCalled();
    expect(ElMessage.success).toHaveBeenCalledWith(expect.stringContaining('重新执行只读校验'));
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
