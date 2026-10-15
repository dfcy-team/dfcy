import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';

const purchaseMocks = vi.hoisted(() => ({ fetchApiFile: vi.fn(), requestApi: vi.fn(), downloadApiFile: vi.fn(), permissions: new Set(['supply.v2.view', 'supply.v2.manage']), routeView: false, success: vi.fn(), error: vi.fn() }));
vi.mock('../src/api/request', () => ({ fetchApiFile: purchaseMocks.fetchApiFile, requestApi: purchaseMocks.requestApi, downloadApiFile: purchaseMocks.downloadApiFile }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: code => purchaseMocks.permissions.has(code), currentUser: null, authorizationStale: false }) }));
vi.mock('../src/router/menu', () => ({ canAccessPath: () => purchaseMocks.routeView }));
vi.mock('element-plus', async original => ({ ...await original(), ElMessage: { error: purchaseMocks.error, success: purchaseMocks.success }, ElMessageBox: { confirm: vi.fn() } }));

import PurchaseProductPreviewV2 from '../src/components/supply-chain/PurchaseProductPreviewV2.vue';
import SupplyProcurementV2 from '../src/views/purchasing/SupplyProcurementV2.vue';

const details = {
  image_url: 'https://remote.example/item.png', specification: '15L', brand: '自有品牌',
  color: '蓝色', material: 'PP', size: 'M', package_length_cm: '20', package_width_cm: '10',
  package_height_cm: '8', package_weight_g: '500.000', spec_values: { 容量: '15L' },
};

const imageStub = {
  props: ['src', 'previewSrcList'],
  template: '<div class="image-preview"><img v-if="src" :src="src" /><slot name="error" /></div>',
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  purchaseMocks.fetchApiFile.mockReset();
  purchaseMocks.requestApi.mockReset();
});

describe('purchase SKU product preview', () => {
  it('loads images through the authorized internal SKU endpoint and shows maintained details', async () => {
    purchaseMocks.fetchApiFile.mockResolvedValue({ success: true, blob: new Blob(['image']) });
    vi.stubGlobal('URL', { createObjectURL: () => 'blob:internal-image', revokeObjectURL: vi.fn() });
    const wrapper = mount(PurchaseProductPreviewV2, {
      props: { skuId: 42, sku: 'NEW-42', legacySkuCode: 'OLD-42', productDetails: details },
      global: { stubs: { 'el-image': imageStub } },
    });
    await flushPromises();

    expect(purchaseMocks.fetchApiFile).toHaveBeenCalledWith('/api/internal/supply-chain/v2/options/skus/42/image/');
    expect(wrapper.find('img').attributes('src')).toBe('blob:internal-image');
    expect(wrapper.text()).toContain('NEW-42');
    expect(wrapper.text()).toContain('OLD-42');
    expect(wrapper.text()).toContain('15L');
    expect(wrapper.text()).toContain('自有品牌');
    expect(wrapper.text()).toContain('20 × 10 × 8 cm');
    wrapper.unmount();

    purchaseMocks.fetchApiFile.mockReset();
  purchaseMocks.requestApi.mockReset();
    purchaseMocks.fetchApiFile.mockResolvedValue({ success: true, blob: new Blob(['frozen']) });
    const existing = mount(PurchaseProductPreviewV2, {
      props: { orderId: 7, skuId: 42, sku: 'NEW-42', legacySkuCode: 'OLD-42', productDetails: details },
      global: { stubs: { 'el-image': imageStub } },
    });
    await flushPromises();
    expect(purchaseMocks.fetchApiFile).toHaveBeenCalledWith('/api/internal/supply-chain/v2/purchase-orders/7/skus/42/image/');
    existing.unmount();
  });


  it('keeps an entered unit price through supplier refresh and saves it on a new purchase', async () => {
    const option = { id: 42, sku: 'NEW-42', legacy_sku_code: 'OLD-42', name: 'Item 42', product_reference_price: '5', supplier_reference_price: '6', product_details: details };
    const savedOrder = { id: 9, supplier_id: 7, country_id: 3, order_date: '2026-10-14', reference_number: '', notes: '', source_kind: 'manual', status: 'draft', version: 1, prices_complete: true, lines: [{ sku_id: 42, sku: 'NEW-42', name: 'Item 42', quantity: 2, unit_price: '7.5000', product_details: details }] };
    purchaseMocks.requestApi.mockImplementation(async request => {
      if (request.url.endsWith('/options/')) return { success: true, data: request.params.kind === 'skus' ? [{ ...option, supplier_reference_price: request.params.supplier_id === 7 ? '8' : '6' }] : [], count: request.params.kind === 'skus' ? 1 : 0 };
      if (request.method === 'post' && request.url.endsWith('/purchase-orders/')) return { success: true, data: savedOrder };
      return { success: true, data: [], count: 0 };
    });
    const wrapper = mount(SupplyProcurementV2, { global: { stubs: {
      'router-link': { template: '<a><slot /></a>' },
      AppPage: { template: '<main><slot name="action" /><slot /></main>' },
      'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button><slot /></button>' },
      'el-alert': { template: '<p />' }, 'el-input': { template: '<input />' }, 'el-input-number': { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<input type="number" :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', Number($event.target.value)); $emit(\'change\', Number($event.target.value))" />' },
      'el-select': { template: '<div><slot /><slot name="footer" /></div>' }, 'el-option': { template: '<option />' },
      'el-tabs': { template: '<div><slot /></div>' }, 'el-tab-pane': { template: '<div><slot /></div>' },
      'el-table': { props: ['data'], provide() { return { testRows: () => this.data || [] }; }, template: '<section><slot /></section>' }, 'el-table-column': { inject: ['testRows'], template: '<div><div v-for="(row, index) in testRows()" :key="index"><slot :row="row" :$index="index" /></div></div>' },
      'el-drawer': { props: ['modelValue'], template: '<aside v-if="modelValue"><slot /><slot name="footer" /></aside>' },
      'el-dialog': { template: '<article><slot /></article>' }, 'el-form': { template: '<form><slot /></form>' }, 'el-form-item': { template: '<label><slot /></label>' },
      'el-tag': { template: '<span><slot /></span>' }, 'el-date-picker': { template: '<input />' }, 'el-switch': { template: '<input />' }, 'el-pagination': { template: '<nav />' },
      SupplierContactsV2: true, PurchaseProductPreviewV2: true,
    }, directives: { loading: () => {} } } });
    await flushPromises();
    wrapper.vm.openCreate();
    wrapper.vm.orderForm.supplier_id = 2;
    wrapper.vm.orderForm.country_id = 3;
    await wrapper.vm.searchSkus('OLD-42');
    wrapper.vm.addLine();
    wrapper.vm.orderForm.lines[0].sku_id = 42;
    wrapper.vm.selectOrderSku(wrapper.vm.orderForm.lines[0]);
    expect(wrapper.vm.orderForm.lines[0].product_details.specification).toBe('15L');
    await flushPromises();
    const priceInput = wrapper.get('input[aria-label="采购单价"]');
    expect(priceInput.element.disabled).toBe(false);
    await priceInput.setValue('7.5');
    wrapper.vm.orderForm.supplier_id = 7;
    await wrapper.vm.changeOrderSupplier();
    expect(wrapper.vm.orderForm.lines[0].unit_price).toBe(7.5);
    await wrapper.vm.saveOrder();
    const create = purchaseMocks.requestApi.mock.calls.map(([request]) => request).find(request => request.method === 'post' && request.url.endsWith('/purchase-orders/'));
    expect(create.data.lines[0].unit_price).toBe(7.5);
    await flushPromises();
    expect(wrapper.findComponent(PurchaseProductPreviewV2).props('orderId')).toBeNull();
    wrapper.vm.selectedOrder.status = 'confirmed';
    await flushPromises();
    expect(wrapper.find('input[aria-label="采购单价"]').exists()).toBe(false);
    expect(wrapper.findComponent(PurchaseProductPreviewV2).props('orderId')).toBe(9);
    wrapper.unmount();
  });

  it('states when maintained specifications and images are missing', async () => {
    const wrapper = mount(PurchaseProductPreviewV2, {
      props: { skuId: 43, sku: 'NEW-43', legacySkuCode: '', productDetails: {} },
      global: { stubs: { 'el-image': imageStub } },
    });
    await flushPromises();
    expect(purchaseMocks.fetchApiFile).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('暂无商品图片');
    expect(wrapper.text()).toContain('旧编码：未维护');
    expect(wrapper.text()).toContain('规格：未维护');
    expect(wrapper.text()).toContain('包装重量：未维护');
    wrapper.unmount();
  });
});
