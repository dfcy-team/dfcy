import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const platformApi = vi.hoisted(() => ({
  bulkUpdatePlatformProductDetails: vi.fn(),
  fetchPlatformProductDetails: vi.fn(),
  importPlatformProductDetails: vi.fn(),
  importPlatformProductIds: vi.fn(),
  updatePlatformProductDetail: vi.fn(),
}));
const integrationsApi = vi.hoisted(() => ({
  fetchConnectionCapabilities: vi.fn(),
  fetchSubjectApiAccess: vi.fn(),
}));
const masterDataApi = vi.hoisted(() => ({ fetchPlatforms: vi.fn(), fetchStores: vi.fn() }));
const productsApi = vi.hoisted(() => ({ fetchProductCategories: vi.fn() }));
const routeState = vi.hoisted(() => ({ query: {} }));
const router = vi.hoisted(() => ({ push: vi.fn() }));
const authPermissions = vi.hoisted(() => new Set([
  'listings.product_detail.view',
  'listings.product_detail.manage',
  'listings.product_detail.import',
  'integrations.product_mapping.view',
  'integrations.view',
  'integrations.store.view',
]));

vi.mock('../src/api/platformProductDetails', () => platformApi);
vi.mock('../src/api/integrations', () => integrationsApi);
vi.mock('../src/api/masterData', () => masterDataApi);
vi.mock('../src/api/products', () => productsApi);
vi.mock('vue-router', () => ({ useRoute: () => routeState, useRouter: () => router }));
vi.mock('../src/api/request', () => ({ useMock: true }));
vi.mock('../src/utils/uiState', () => ({ statusFromApiResponse: () => 'forbidden' }));
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (permission) => authPermissions.has(permission),
    isModuleEnabled: () => true,
  }),
}));

import PlatformProductDetailList from '../src/views/masterdata/PlatformProductDetailList.vue';

const stubs = {
  AppPage: { template: '<main><slot name="action" /><slot /></main>' },
  AppState: { template: '<div class="app-state"><slot /></div>' },
  ProductMappingPanel: { template: '<div class="mapping-panel-stub" />' },
  'el-alert': { props: { title: String, description: String }, template: '<div class="alert">{{ title }}{{ description }}</div>' },
  'el-button': { props: { disabled: Boolean, loading: Boolean }, emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-dialog': { props: { modelValue: Boolean }, template: '<div v-if="modelValue" class="dialog"><slot /><slot name="footer" /></div>' },
  'el-divider': { template: '<hr />' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: { label: String }, template: '<label>{{ label }}<slot /></label>' },
  'el-input': { props: { modelValue: String, disabled: Boolean }, emits: ['update:modelValue'], template: '<input :disabled="disabled" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-pagination': { template: '<nav />' },
  'el-radio': { template: '<span><slot /></span>' },
  'el-radio-group': { template: '<div><slot /></div>' },
  'el-select': { template: '<select><slot /></select>' },
  'el-option': { template: '<option><slot /></option>' },
  'el-step': { template: '<span />' },
  'el-steps': { template: '<div><slot /></div>' },
  'el-tab-pane': { template: '<div />' },
  'el-tabs': { template: '<div><slot /></div>' },
  'el-table': { template: '<div><slot /></div>' },
  'el-table-column': { template: '<div />' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-tree': { template: '<div />' },
};

const mappedRow = {
  id: 704,
  platform_name: 'Shopee',
  platform_variant_id: 'demo-variant-004',
  platform_product_id: 'demo-product-004',
  platform_sku: 'DEMO-SKU-004',
  source_old_sku_code: 'OLD-004',
  internal_legacy_sku_code: 'OLD-004',
  internal_sku_code: 'SKU-DEMO-004',
  store_id: 1,
  store_name: '新加坡示例店铺',
  platform_code: 'shopee',
  platform_updated_at: '2026-09-05T10:00:00Z',
  updated_at: '2026-09-05T10:05:00Z',
  title: '原商品标题',
  variant: '500ml',
  sales_status: 'active',
  owner: '演示运营',
  leader: '演示负责人',
  mapping: {
    id: 404,
    status: 'mapped',
    mapping_source: 'api_exact_match',
    manually_confirmed: false,
    sku_id: 14,
    sku_code: 'SKU-DEMO-004',
  },
};

function detailsResponse() {
  return {
    success: true,
    code: 'OK',
    message: 'ok',
    data: { count: 1, next: null, previous: null, results: [{ ...mappedRow }], api_status: 'mock' },
  };
}

async function mountPage() {
  const wrapper = mount(PlatformProductDetailList, { global: { stubs } });
  await flushPromises();
  return wrapper;
}

describe('平台商品明细受控编辑运行时回归', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authPermissions.add('integrations.view');
    authPermissions.add('integrations.store.view');
    routeState.query = {};
    masterDataApi.fetchPlatforms.mockResolvedValue({ success: true, data: { results: [] } });
    masterDataApi.fetchStores.mockResolvedValue({ success: true, data: { results: [] } });
    productsApi.fetchProductCategories.mockResolvedValue({ success: true, data: { results: [] } });
    platformApi.fetchPlatformProductDetails.mockResolvedValue(detailsResponse());
    platformApi.updatePlatformProductDetail.mockResolvedValue({ success: true, code: 'OK', message: 'ok', data: mappedRow });
    integrationsApi.fetchSubjectApiAccess.mockResolvedValue({
      success: true,
      data: { bindings: [{ id: 201, api_type: 'marketplace', platform: 'shopee', status: 'active' }] },
    });
    integrationsApi.fetchConnectionCapabilities.mockResolvedValue({
      success: true,
      data: { results: [{ capability_code: 'PRODUCT', read_enabled: true, write_enabled: false, status: 'active' }] },
    });
  });

  it('已映射明细只修改标题时只提交标题字段', async () => {
    const wrapper = await mountPage();
    wrapper.vm.openEdit(mappedRow);
    expect(wrapper.vm.editControlled).toBe(true);
    wrapper.vm.editForm.title = '修改后的商品标题';

    await wrapper.vm.saveEdit();
    await flushPromises();

    expect(platformApi.updatePlatformProductDetail).toHaveBeenCalledWith(704, { title: '修改后的商品标题' });
    expect(wrapper.vm.editSaving).toBe(false);
  });

  it('distinguishes source and local SKU identity while exposing the guarded product sync route', async () => {
    const wrapper = await mountPage();
    expect(wrapper.vm.skuIdentityStateLabel(mappedRow)).toBe('自动精确关联');
    expect(wrapper.vm.sourceLabel(mappedRow.source)).toBe('未标明');
    expect(wrapper.vm.formatDateTime(mappedRow.platform_updated_at)).not.toBe('未同步');

    await wrapper.vm.openProductSync(mappedRow);
    await flushPromises();

    expect(integrationsApi.fetchSubjectApiAccess).toHaveBeenCalledWith('store', 1);
    expect(integrationsApi.fetchConnectionCapabilities).toHaveBeenCalledWith(201);
    expect(router.push).toHaveBeenCalledWith({
      path: '/integrations/sync-jobs',
      query: expect.objectContaining({
        platform: 'shopee',
        api_type: 'marketplace',
        resource_type: 'platform_product',
        store_id: '1',
      }),
    });
  });

  it('does not expose the sync action to a role without integration view permissions', async () => {
    authPermissions.delete('integrations.view');
    const wrapper = await mountPage();

    expect(wrapper.vm.canViewSync).toBe(false);
    await wrapper.vm.openProductSync(mappedRow);
    expect(integrationsApi.fetchSubjectApiAccess).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
  });
});
