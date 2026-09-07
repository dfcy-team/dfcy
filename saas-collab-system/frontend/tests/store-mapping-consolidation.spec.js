import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ElMessage, ElMessageBox } from 'element-plus';
import { inject, provide, toRef } from 'vue';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const authState = vi.hoisted(() => ({
  master: true,
  view: true,
  manage: true,
  moduleStatus: 'enabled',
  integrationView: true,
  storeView: true,
}));
const api = vi.hoisted(() => ({
  fetchStoreMappingOptions: vi.fn(),
  fetchStoreMappings: vi.fn(),
  createStoreMapping: vi.fn(),
  updateStoreMapping: vi.fn(),
  fetchConnectionCapabilities: vi.fn(),
  fetchStoreAuthorizations: vi.fn(),
  fetchSubjectApiAccess: vi.fn(),
  updateConnectionCapabilities: vi.fn(),
}));
const masterDataApi = vi.hoisted(() => ({
  applyPlatformSiteMigration: vi.fn(),
  createMasterData: vi.fn(),
  deleteMasterData: vi.fn(),
  fetchCountrySites: vi.fn(),
  fetchMasterDataDetail: vi.fn(),
  fetchPlatforms: vi.fn(),
  fetchPlatformSiteMigrationPreview: vi.fn(),
  fetchPlatformSites: vi.fn(),
  fetchStores: vi.fn(),
  importStores: vi.fn(),
  updateMasterData: vi.fn(),
  updateMasterDataStatus: vi.fn(),
}));
const systemAdminApi = vi.hoisted(() => ({ fetchUsers: vi.fn() }));
const productsApi = vi.hoisted(() => ({ fetchProductCategories: vi.fn() }));
const routeState = vi.hoisted(() => ({ query: {} }));
const routerPush = vi.hoisted(() => vi.fn());

vi.mock('../src/api/integrations', () => api);
vi.mock('../src/api/masterData', () => masterDataApi);
vi.mock('../src/api/systemAdmin', () => systemAdminApi);
vi.mock('../src/api/products', () => productsApi);
vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: routerPush }),
}));
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    moduleStatuses: { api_integrations: authState.moduleStatus },
    isModuleEnabled: () => authState.moduleStatus !== 'disabled',
    hasPermission: (permission) => {
      if (permission === 'masterdata.view') return authState.master;
      if (permission === 'integrations.store_mapping.view') return authState.view;
      if (permission === 'integrations.store_mapping.manage') return authState.manage;
      if (permission === 'integrations.view') return authState.integrationView;
      if (permission === 'integrations.store.view') return authState.storeView;
      return false;
    },
  }),
}));
vi.mock('../src/utils/actionAccess', () => ({
  getActionAccess: (auth, { permission, unauthorizedBehavior }) => {
    const allowed = auth.hasPermission(permission);
    return {
      allowed,
      visible: allowed || unauthorizedBehavior === 'disable',
      disabled: !allowed,
      reason: allowed ? '' : `缺少权限：${permission}`,
    };
  },
}));

import StoreMappingPanel from '../src/components/StoreMappingPanel.vue';
import StoreMappingList from '../src/views/integrations/StoreMappingList.vue';
import StoreMasterList from '../src/views/masterdata/StoreMasterList.vue';

const stubs = {
  'el-button': {
    props: { disabled: Boolean, loading: Boolean, title: String, type: String },
    emits: ['click'],
    template: '<button :disabled="disabled" :title="title" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  'el-alert': { props: { title: String, description: String }, template: '<div class="alert">{{ title }}{{ description }}</div>' },
  'el-tag': { template: '<span class="tag"><slot /></span>' },
  'el-table': {
    props: { data: { type: Array, default: () => [] } },
    setup(props) { provide('store-mapping-test-rows', toRef(props, 'data')); },
    template: '<div class="table"><slot /></div>',
  },
  'el-table-column': {
    props: { label: String },
    setup() { return { rows: inject('store-mapping-test-rows', []) }; },
    template: '<div class="table-column" :data-label="label"><div v-for="row in rows" :key="row.id"><slot :row="row" /></div></div>',
  },
  'el-select': {
    props: { modelValue: [String, Number], disabled: Boolean },
    emits: ['update:modelValue', 'change'],
    template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>',
  },
  'el-option': { props: { label: String, value: [String, Number] }, template: '<option :value="value">{{ label }}</option>' },
  'el-pagination': { template: '<div class="pagination" />' },
  'el-dialog': { props: { modelValue: Boolean, title: String }, template: '<div v-if="modelValue" class="dialog"><slot /><slot name="footer" /></div>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: { label: String }, template: '<label><slot /></label>' },
};

function optionsResponse(overrides = {}) {
  return {
    success: true,
    data: {
      stores: [{ id: 1, code: 'demo-store-sg', name: '新加坡示例店铺', platform: 'shopee', platform_name: 'Shopee' }],
      authorizations: [{
        id: 201,
        store_id: 1,
        platform: 'shopee',
        region: 'SG',
        status: 'active',
        platform_store_id_masked: 'masked-external-store-001',
        store_name: '新加坡示例店铺',
      }],
      store_mappings: [{
        id: 301,
        store_id: 1,
        store_code: 'demo-store-sg',
        store_name: '新加坡示例店铺',
        platform: 'shopee',
        platform_store_id: 'masked-external-store-001',
        region: 'SG',
        status: 'active',
        mapping_source: 'oauth_callback',
        last_verified_at: '2026-09-01T09:00:00Z',
      }],
      ...overrides,
    },
  };
}

async function mountPanel(props = {}) {
  const wrapper = mount(StoreMappingPanel, {
    props: { store: { id: 1, code: 'demo-store-sg', name: '新加坡示例店铺', platform: 'shopee' }, ...props },
    global: { stubs },
  });
  await flushPromises();
  return wrapper;
}

describe('店铺平台关联归集面板', () => {
  beforeEach(() => {
    authState.master = true;
    authState.view = true;
    authState.manage = true;
    authState.moduleStatus = 'enabled';
    authState.integrationView = true;
    authState.storeView = true;
    api.fetchStoreMappingOptions.mockReset().mockResolvedValue(optionsResponse());
    api.fetchStoreMappings.mockReset().mockResolvedValue({ success: true, data: { count: 1, results: optionsResponse().data.store_mappings } });
    api.createStoreMapping.mockReset().mockResolvedValue({ success: true, data: { id: 302 } });
    api.updateStoreMapping.mockReset().mockResolvedValue({ success: true, data: { id: 301, status: 'inactive' } });
    api.fetchConnectionCapabilities.mockReset().mockResolvedValue({ success: true, data: { results: [] } });
    api.fetchStoreAuthorizations.mockReset().mockResolvedValue({ success: true, data: { results: [] } });
    api.fetchSubjectApiAccess.mockReset().mockResolvedValue({ success: true, data: { bindings: [] } });
    api.updateConnectionCapabilities.mockReset().mockResolvedValue({ success: true, data: {} });
    Object.values(masterDataApi).forEach((fn) => fn.mockReset().mockResolvedValue({ success: true, data: { results: [], count: 0 } }));
    systemAdminApi.fetchUsers.mockReset().mockResolvedValue({ success: true, data: { results: [] } });
    productsApi.fetchProductCategories.mockReset().mockResolvedValue({ success: true, data: { results: [] } });
    routeState.query = {};
    routerPush.mockReset();
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(true);
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined);
  });

  it('带入店铺上下文读取关联，并展示授权身份、来源、验证时间和状态', async () => {
    const wrapper = await mountPanel();
    expect(api.fetchStoreMappingOptions).toHaveBeenCalledWith(expect.objectContaining({ store_id: 1 }));
    expect(wrapper.text()).toContain('新加坡示例店铺');
    expect(wrapper.text()).toContain('授权 #201');
    expect(wrapper.text()).toContain('OAuth 回调');
    expect(wrapper.text()).toContain('启用');
  });

  it('API 接入入口同时受 integrations.view 与 integrations.store.view 控制并显示权限原因', async () => {
    authState.integrationView = false;
    const wrapper = await mountPanel();
    const apiButton = wrapper.findAll('button').find((item) => item.text() === 'API 接入');
    expect(apiButton.exists()).toBe(true);
    expect(apiButton.attributes('disabled')).toBeDefined();
    expect(apiButton.attributes('title')).toContain('integrations.view');
  });

  it('创建关联只能选择授权身份并发送服务端允许的字段', async () => {
    const wrapper = await mountPanel();
    const create = wrapper.findAll('button').find((item) => item.text().includes('新建平台关联'));
    expect(create.exists()).toBe(true);
    await create.trigger('click');
    await flushPromises();
    const authorization = wrapper.findAll('select').find((item) => item.attributes('disabled') === undefined);
    expect(authorization.exists()).toBe(true);
    await authorization.setValue('201');
    const submit = wrapper.findAll('button').find((item) => item.text().includes('确认建立关联'));
    await submit.trigger('click');
    await flushPromises();
    expect(api.createStoreMapping).toHaveBeenCalledWith(expect.objectContaining({ store_id: 1, authorization_id: 201 }));
    expect(api.createStoreMapping.mock.calls[0][0]).not.toHaveProperty('platform_store_id');
  });

  it('支持成功停用关联，并在接口失败时保留可见错误', async () => {
    const wrapper = await mountPanel();
    const disable = wrapper.findAll('button').find((item) => item.text() === '停用');
    expect(disable.exists()).toBe(true);
    await disable.trigger('click');
    await flushPromises();
    expect(api.updateStoreMapping).toHaveBeenCalledWith(301, { status: 'inactive' });

    api.updateStoreMapping.mockResolvedValueOnce({ success: false, message: '映射状态更新失败' });
    await disable.trigger('click');
    await flushPromises();
    expect(ElMessage.error).toHaveBeenCalledWith('映射状态更新失败');
  });

  it('无查看权限或 API 模块关闭时不读取数据并禁用维护按钮', async () => {
    authState.view = false;
    const denied = await mountPanel();
    expect(api.fetchStoreMappingOptions).not.toHaveBeenCalled();
    expect(denied.text()).toContain('没有查看店铺平台关联的权限');

    authState.view = true;
    authState.moduleStatus = 'disabled';
    const disabled = await mountPanel();
    expect(api.fetchStoreMappingOptions).not.toHaveBeenCalled();
    const create = disabled.findAll('button').find((item) => item.text().includes('新建平台关联'));
    expect(create.attributes('disabled')).toBeDefined();
  });

  it('旧兼容壳只复用归集面板并支持 store_id 上下文', async () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/integrations/StoreMappingList.vue'), 'utf8');
    expect(source).toContain("import StoreMappingPanel from '../../components/StoreMappingPanel.vue'");
    expect(source).toContain(':store-id="route.query.store_id || null"');
    expect(source).not.toContain('createForm');
    expect(StoreMappingList).toBeTruthy();
  });

  it('独立入口可远程检索首屏之外的店铺和有效授权选项', async () => {
    const wrapper = await mountPanel({ standalone: true });
    api.fetchStoreMappingOptions.mockResolvedValueOnce(optionsResponse({
      stores: [{ id: 1001, code: 'store-1001', name: '远端店铺 1001', platform: 'shopee', platform_name: 'Shopee' }],
      authorizations: [],
    }));
    await wrapper.vm.searchStores('store-1001');
    expect(api.fetchStoreMappingOptions).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'store-1001', page: 1, page_size: 100 }));

    api.fetchStoreMappingOptions.mockResolvedValueOnce(optionsResponse({
      stores: [],
      authorizations: [{ id: 1201, store_id: 1, platform: 'shopee', region: 'SG', status: 'active', platform_store_id_masked: 'masked-1201' }],
    }));
    await wrapper.vm.searchAuthorizations('masked-1201');
    expect(api.fetchStoreMappingOptions).toHaveBeenLastCalledWith(expect.objectContaining({ store_id: 1, search: 'masked-1201', page: 1, page_size: 100 }));
  });

  it('宿主工作区按点击的店铺行带入映射上下文并读取真实 API 授权', async () => {
    api.fetchSubjectApiAccess.mockResolvedValueOnce({
      success: true,
      data: {
        bindings: [{
          id: 201,
          status: 'active',
          account_alias: 'demo-shopee',
          platform_store_id: 'masked-store-001',
          last_verified_at: '2026-09-01T09:00:00Z',
        }],
      },
    });
    const row = { id: 1, code: 'demo-store-sg', name: '新加坡示例店铺', platform: 'shopee', status: 'active' };
    const wrapper = mount(StoreMasterList, {
      global: {
        stubs: {
          ...stubs,
          AdminResourcePage: {
            setup() { return { row }; },
            template: '<div class="admin-resource-stub"><slot name="row-actions" :row="row" /></div>',
          },
          StoreMappingPanel: {
            props: { store: Object, storeId: [String, Number], standalone: Boolean },
            template: '<div class="mapping-host-panel" :data-store-id="String(store?.id || storeId || \'\')" />',
          },
          SubjectApiAccessDialog: { template: '<div class="subject-api-stub" />' },
          'el-drawer': { props: { modelValue: Boolean }, template: '<div v-if="modelValue" class="drawer-stub"><slot /></div>' },
          'el-tabs': { template: '<div><slot /></div>' },
          'el-tab-pane': { template: '<section><slot /></section>' },
          'el-descriptions': { template: '<div><slot /></div>' },
          'el-descriptions-item': { template: '<div><slot /></div>' },
        },
      },
    });
    await flushPromises();
    const mappingButton = wrapper.findAll('button').find((button) => button.text() === '平台关联');
    expect(mappingButton).toBeTruthy();
    await mappingButton.trigger('click');
    await flushPromises();
    expect(wrapper.find('.mapping-host-panel').attributes('data-store-id')).toBe('1');
    expect(api.fetchSubjectApiAccess).toHaveBeenCalledWith('store', 1);
  });

  it('宿主深链按主档详情 ID 读取，不依赖前 100 条店铺列表', async () => {
    routeState.query = { store_id: '101', panel: 'mapping' };
    masterDataApi.fetchMasterDataDetail.mockResolvedValueOnce({
      success: true,
      data: { id: 101, code: 'store-0101', name: '第 101 家店铺', platform: 'shopee', status: 'active' },
    });
    const wrapper = mount(StoreMasterList, {
      global: {
        stubs: {
          ...stubs,
          AdminResourcePage: { template: '<div class="admin-resource-stub" />' },
          StoreMappingPanel: {
            props: { store: Object, storeId: [String, Number], standalone: Boolean },
            template: '<div class="mapping-host-panel" :data-store-id="String(store?.id || storeId || \'\')" />',
          },
          SubjectApiAccessDialog: { template: '<div class="subject-api-stub" />' },
          'el-drawer': { props: { modelValue: Boolean }, template: '<div v-if="modelValue"><slot /></div>' },
          'el-tabs': { template: '<div><slot /></div>' },
          'el-tab-pane': { template: '<section><slot /></section>' },
          'el-descriptions': { template: '<div><slot /></div>' },
          'el-descriptions-item': { template: '<div><slot /></div>' },
        },
      },
    });
    await flushPromises();
    expect(masterDataApi.fetchMasterDataDetail).toHaveBeenCalledWith('stores', 101);
    expect(masterDataApi.fetchStores).not.toHaveBeenCalled();
    expect(wrapper.find('.mapping-host-panel').attributes('data-store-id')).toBe('101');
  });

  it('mapping-only 宿主只挂载关联面板，不请求店铺和引用主档接口', async () => {
    authState.master = false;
    authState.view = true;
    authState.integrationView = false;
    authState.storeView = false;
    const wrapper = mount(StoreMasterList, {
      global: {
        stubs: {
          ...stubs,
          AdminResourcePage: { template: '<div class="admin-resource-should-not-mount" />' },
          StoreMappingPanel: {
            props: { store: Object, storeId: [String, Number], standalone: Boolean },
            template: '<div class="mapping-only-stub" :data-store-id="String(store?.id || storeId || \'\')" />',
          },
          SubjectApiAccessDialog: { template: '<div class="subject-api-stub" />' },
          'el-drawer': { props: { modelValue: Boolean }, template: '<div v-if="modelValue"><slot /></div>' },
        },
      },
    });
    await flushPromises();
    expect(wrapper.find('.mapping-only-stub').exists()).toBe(true);
    expect(wrapper.find('.admin-resource-should-not-mount').exists()).toBe(false);
    expect(masterDataApi.fetchStores).not.toHaveBeenCalled();
    expect(masterDataApi.fetchPlatforms).not.toHaveBeenCalled();
    expect(masterDataApi.fetchPlatformSites).not.toHaveBeenCalled();
    expect(masterDataApi.fetchCountrySites).not.toHaveBeenCalled();
    expect(productsApi.fetchProductCategories).not.toHaveBeenCalled();
    expect(systemAdminApi.fetchUsers).not.toHaveBeenCalled();
  });
});
