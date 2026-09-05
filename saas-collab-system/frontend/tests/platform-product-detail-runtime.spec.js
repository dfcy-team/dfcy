import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const platformApi = vi.hoisted(() => ({
  bulkUpdatePlatformProductDetails: vi.fn(),
  fetchPlatformProductDetails: vi.fn(),
  importPlatformProductDetails: vi.fn(),
  importPlatformProductIds: vi.fn(),
  updatePlatformProductDetail: vi.fn(),
}));
const masterDataApi = vi.hoisted(() => ({ fetchPlatforms: vi.fn(), fetchStores: vi.fn() }));
const productsApi = vi.hoisted(() => ({ fetchProductCategories: vi.fn() }));
const routeState = vi.hoisted(() => ({ query: {} }));

vi.mock('../src/api/platformProductDetails', () => platformApi);
vi.mock('../src/api/masterData', () => masterDataApi);
vi.mock('../src/api/products', () => productsApi);
vi.mock('vue-router', () => ({ useRoute: () => routeState }));
vi.mock('../src/api/request', () => ({ useMock: true }));
vi.mock('../src/utils/uiState', () => ({ statusFromApiResponse: () => 'forbidden' }));
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (permission) => [
      'listings.product_detail.view',
      'listings.product_detail.manage',
      'listings.product_detail.import',
      'integrations.product_mapping.view',
    ].includes(permission),
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
  title: '原商品标题',
  variant: '500ml',
  sales_status: 'active',
  owner: '演示运营',
  leader: '演示负责人',
  mapping: { id: 404, status: 'mapped', sku_id: 14, sku_code: 'SKU-DEMO-004' },
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
    routeState.query = {};
    masterDataApi.fetchPlatforms.mockResolvedValue({ success: true, data: { results: [] } });
    masterDataApi.fetchStores.mockResolvedValue({ success: true, data: { results: [] } });
    productsApi.fetchProductCategories.mockResolvedValue({ success: true, data: { results: [] } });
    platformApi.fetchPlatformProductDetails.mockResolvedValue(detailsResponse());
    platformApi.updatePlatformProductDetail.mockResolvedValue({ success: true, code: 'OK', message: 'ok', data: mappedRow });
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
});
