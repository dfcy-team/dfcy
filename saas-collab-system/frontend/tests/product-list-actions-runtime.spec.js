import { computed, defineComponent, h, ref } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  fetchProductDetailList: vi.fn(),
  fetchProductCategories: vi.fn(),
  fetchProductCategoryBackgroundColors: vi.fn(),
  fetchProductColors: vi.fn(),
  fetchProductAttributes: vi.fn(),
  deleteProductSku: vi.fn(),
  deleteProductLegacyItem: vi.fn(),
  updateProductSkuStatus: vi.fn(),
  fetchProductMasterList: vi.fn(),
  deleteProductSpu: vi.fn(),
}));

vi.mock('../src/api/products', () => ({
  ...Object.fromEntries([
    'fetchProductBundleDetail', 'exportProductDetails', 'importLegacyProductItems', 'updateLegacyProductItem',
    'generateLegacyProductItem', 'updateProductSku', 'bulkUpdateProductDetails', 'bulkCacheProductImages',
    'createProductSpu', 'exportProductMaster', 'recodeProductSpus', 'updateProductSpu', 'updateProductSpuStatus',
    'bulkUpdateProductSpus',
  ].map((name) => [name, vi.fn()])),
  ...api,
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: {}, hasPermission: () => true }) }));
vi.mock('../src/utils/useCompactViewport', () => ({ useCompactViewport: () => ref(false) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('element-plus', async (importOriginal) => ({
  ...(await importOriginal()),
  ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) },
}));
vi.mock('../src/utils/businessResponse', () => ({
  apiState: () => 'connected',
  collectionRows: (data) => data?.results || [],
  collectionTotal: (data) => data?.count || 0,
  detailData: (data) => data,
  stateTagType: () => 'success',
}));
vi.mock('../src/utils/apiBaseUrl', () => ({ apiBaseUrl: '' }));
vi.mock('../src/api/baseUrl', () => ({ apiBaseUrl: '' }));
vi.mock('../src/utils/productCategoryPresentation', () => ({
  buildCategoryTree: (rows) => rows,
  categoryRowClass: () => '',
  categoryRowStyle: () => ({}),
  mergeCategoryBackgroundColors: (rows) => rows,
}));
vi.mock('../src/utils/productDictionaryCache', () => ({
  getProductDictionaryCache: () => ({ value: { categories: [], colors: [], attributes: [] }, version: 1, promise: null }),
  productDictionaryCacheScope: () => 'test',
  subscribeProductDictionaryCacheInvalidation: () => () => {},
}));
vi.mock('../src/utils/imageBatchCsv', () => ({ parseImageCsv: vi.fn(), yieldToPage: vi.fn() }));
vi.mock('../src/utils/bigsellerWorkbook', () => ({ downloadBigSellerBundleWorkbook: vi.fn(), downloadBigSellerProductWorkbook: vi.fn() }));

const tableClear = vi.fn();
const tableToggle = vi.fn();
const tableSetSelection = vi.fn();
let tableApi;
const TableStub = defineComponent({
  props: { data: { type: Array, default: () => [] }, rowKey: [Function, String] },
  emits: ['selection-change', 'sort-change'],
  setup(props, { emit, expose, slots }) {
    const selection = ref([]);
    const keyFor = (item) => typeof props.rowKey === 'function' ? props.rowKey(item) : item?.[props.rowKey];
    const clearSelection = () => { tableClear(); selection.value = []; emit('selection-change', []); };
    const toggleRowSelection = (row, selected) => {
      tableToggle(row, selected, keyFor(row));
      const key = keyFor(row);
      selection.value = selected
        ? [...selection.value.filter((item) => keyFor(item) !== key), row]
        : selection.value.filter((item) => keyFor(item) !== key);
      emit('selection-change', selection.value);
    };
    const setSelection = (rows) => { tableSetSelection(rows); selection.value = rows; emit('selection-change', rows); };
    const isSelected = (row) => selection.value.some((item) => keyFor(item) === keyFor(row));
    const selectedRows = () => [...selection.value];
    tableApi = { clearSelection, toggleRowSelection, setSelection, isSelected, selectedRows };
    expose(tableApi);
    return () => h('div', { 'data-testid': 'stub-table' }, [
      ...props.data.map((row) => h('div', {
        'data-row-id': String(row.id ?? row.sku_id),
        'data-selected': isSelected(row) ? 'true' : 'false',
      })),
      slots.default?.(),
    ]);
  },
});
const ButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  setup(_, { attrs, emit, slots }) { return () => h('button', { ...attrs, onClick: (event) => emit('click', event) }, slots.default?.()); },
});
const DialogStub = defineComponent({
  props: { modelValue: Boolean },
  setup(props, { slots }) { return () => props.modelValue ? h('div', { class: 'test-dialog' }, [slots.default?.(), slots.footer?.()]) : null; },
});
const PaginationStub = defineComponent({
  emits: ['current-change'],
  setup(_, { emit }) {
    return () => h('div', [
      h('button', { 'data-testid': 'page-one', onClick: () => emit('current-change', 1) }, '1'),
      h('button', { 'data-testid': 'page-three', onClick: () => emit('current-change', 3) }, '3'),
    ]);
  },
});
const GenericStub = defineComponent({ setup(_, { slots }) { return () => h('div', slots.default?.()); } });

import ProductDetailData from '../src/views/products/ProductDetailData.vue';
import ProductMasterList from '../src/views/products/ProductMasterList.vue';

let wrapper;
const legacy = { id: 17, row_type: 'legacy', legacy_sku_code: 'OLD-17' };
const sku = { id: 17, sku_id: 901, row_type: 'sku', sku_code: 'NEW-17' };
const legacyOtherPage = { id: 26, row_type: 'legacy', legacy_sku_code: 'OLD-26' };

function mountPage() {
  api.fetchProductDetailList.mockResolvedValue({ success: true, data: { results: [legacy, sku], count: 2 } });
  api.fetchProductCategories.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  api.fetchProductCategoryBackgroundColors.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  api.fetchProductColors.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  api.fetchProductAttributes.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  wrapper = mount(ProductDetailData, {
    attachTo: document.body,
    global: {
      stubs: {
        'router-link': GenericStub,
        'el-table': TableStub,
        'el-button': ButtonStub,
        'el-dialog': DialogStub,
        'el-pagination': PaginationStub,
        'el-table-column': true,
        'el-dropdown': GenericStub,
        'el-dropdown-menu': GenericStub,
        'el-dropdown-item': GenericStub,
        'el-form': GenericStub,
        'el-form-item': GenericStub,
        'el-input': GenericStub,
        'el-select': GenericStub,
        'el-option': GenericStub,
        'el-segmented': GenericStub,
        'el-alert': GenericStub,
        'el-tag': GenericStub,
        'el-image': GenericStub,
        'el-checkbox': GenericStub,
        'el-checkbox-group': GenericStub,
        'el-radio': GenericStub,
        'el-radio-group': GenericStub,
        'el-progress': GenericStub,
        'el-upload': GenericStub,
        'el-tooltip': GenericStub,
        'el-popover': GenericStub,
        'el-date-picker': GenericStub,
        'el-tree': GenericStub,
        'el-divider': GenericStub,
        SpuCodeDisplay: true,
        ProductBundleManager: true,
      },
    },
  });
}

function mountMasterPage() {
  api.fetchProductCategories.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  api.fetchProductCategoryBackgroundColors.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  api.fetchProductColors.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  api.fetchProductAttributes.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  wrapper = mount(ProductMasterList, {
    attachTo: document.body,
    global: {
      stubs: {
        'router-link': GenericStub,
        'el-table': TableStub,
        'el-button': ButtonStub,
        'el-dialog': DialogStub,
        'el-pagination': PaginationStub,
        'el-table-column': true,
        'el-tree': GenericStub,
        'el-dropdown': GenericStub,
        'el-dropdown-menu': GenericStub,
        'el-dropdown-item': GenericStub,
        'el-form': GenericStub,
        'el-form-item': GenericStub,
        'el-input': GenericStub,
        'el-select': GenericStub,
        'el-option': GenericStub,
        'el-alert': GenericStub,
        'el-tag': GenericStub,
        'el-popover': GenericStub,
        'el-tooltip': GenericStub,
        'SpuCodeDisplay': true,
        'SkuGenerationDialog': true,
      },
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  api.deleteProductSku.mockResolvedValue({ success: true });
  api.deleteProductLegacyItem
    .mockResolvedValueOnce({ success: false, message: '该旧档案仍被引用' })
    .mockResolvedValue({ success: false, code: 'HTTP_NETWORK_ERROR', message: '网关超时' });
  api.fetchProductMasterList.mockResolvedValue({ success: true, data: { results: [], count: 0 } });
  api.deleteProductSpu.mockResolvedValue({ success: true });
});
afterEach(() => { wrapper?.unmount(); wrapper = null; tableApi = null; document.body.innerHTML = ''; });

describe('商品明细列表批量删除与排序行为', () => {
  it('区分相同 id 的旧档案和 SKU；部分失败保留复合键选择、完整原因且不自动停用', async () => {
    mountPage();
    await flushPromises();
    const table = wrapper.findComponent(TableStub);
    expect(table.props('rowKey')(legacy)).toBe('legacy:17');
    expect(table.props('rowKey')(sku)).toBe('sku:17');

    table.vm.$emit('selection-change', [legacy, sku, legacyOtherPage]);
    await flushPromises();
    await wrapper.find('[data-testid="product-detail-bulk-delete"]').trigger('click');
    await flushPromises();

    expect(api.deleteProductLegacyItem).toHaveBeenCalledWith(17);
    expect(api.deleteProductLegacyItem).toHaveBeenCalledWith(26);
    expect(api.deleteProductSku).toHaveBeenCalledWith(901);
    expect(api.updateProductSkuStatus).not.toHaveBeenCalled();
    expect(tableClear).toHaveBeenCalledOnce();
    expect(tableToggle).toHaveBeenCalledTimes(2);
    expect(tableToggle).toHaveBeenCalledWith(legacy, true, 'legacy:17');
    expect(tableToggle).toHaveBeenCalledWith(legacyOtherPage, true, 'legacy:26');
    expect(wrapper.find('.test-dialog').text()).toContain('该旧档案仍被引用');
    expect(wrapper.find('.test-dialog').text()).toContain('请求结果未能确认');
    expect(wrapper.find('.test-dialog').text()).toContain('成功删除 1 条，2 条未能删除');
  });

  it('排序发送 ordering 并回第一页，清除排序恢复默认请求', async () => {
    mountPage();
    await flushPromises();
    await wrapper.find('[data-testid="page-three"]').trigger('click');
    await flushPromises();
    const table = wrapper.findComponent(TableStub);
    table.vm.$emit('sort-change', { prop: 'legacy_sku_code', order: 'descending' });
    await flushPromises();
    expect(api.fetchProductDetailList).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, ordering: '-legacy_sku_code' }));

    table.vm.$emit('sort-change', { prop: null, order: null });
    await flushPromises();
    expect(api.fetchProductDetailList).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, ordering: undefined }));
  });
});

describe('商品主数据批量删除选择状态', () => {
  it('成功项不会残留在表格选择中，失败引用显示实际引用名', async () => {
    const itemA = { id: 71, spu_code: 'SPU-A' };
    const itemB = { id: 72, spu_code: 'SPU-B' };
    const itemC = { id: 73, spu_code: 'SPU-C' };
    const offPageFailure = { id: 74, spu_code: 'SPU-OFF-PAGE' };
    api.fetchProductMasterList
      .mockResolvedValueOnce({ success: true, data: { results: [itemA, itemB, itemC], count: 3 } })
      .mockResolvedValueOnce({ success: true, data: { results: [itemB, itemC], count: 2 } })
      .mockResolvedValueOnce({ success: true, data: { results: [offPageFailure], count: 3 } })
      .mockResolvedValueOnce({ success: true, data: { results: [itemB, itemC], count: 3 } })
      .mockResolvedValue({ success: true, data: { results: [], count: 0 } });
    api.deleteProductSpu
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({
        success: false,
        http_status: 409,
        message: '删除失败',
        data: { references: ['订单明细', '刊登记录'], can_deactivate: true },
      })
      .mockResolvedValueOnce({
        success: false,
        http_status: 409,
        message: '删除失败',
        data: { references: ['未完成任务'], can_deactivate: true },
      })
      .mockResolvedValue({ success: true });

    mountMasterPage();
    await flushPromises();
    const table = wrapper.findComponent(TableStub);
    tableApi.setSelection([itemA, itemB, offPageFailure]);
    await flushPromises();
    await wrapper.find('[data-testid="product-master-bulk-delete"]').trigger('click');
    await flushPromises();

    expect(api.deleteProductSpu.mock.calls.slice(0, 3)).toEqual([[71], [72], [74]]);
    expect(tableClear).toHaveBeenCalledOnce();
    expect(tableToggle).toHaveBeenCalledWith(itemB, true, 72);
    expect(tableToggle).toHaveBeenCalledWith(offPageFailure, true, 74);
    expect(tableApi.selectedRows().map((row) => row.id)).toEqual([72, 74]);
    expect(wrapper.find('.test-dialog').text()).toContain('订单明细、刊登记录');
    expect(wrapper.find('.test-dialog').text()).not.toContain('删除失败');

    await wrapper.find('[data-testid="page-three"]').trigger('click');
    await flushPromises();
    expect(tableApi.isSelected(offPageFailure)).toBe(true);
    expect(wrapper.find('[data-row-id="74"]').attributes('data-selected')).toBe('true');
    await wrapper.find('[data-testid="page-one"]').trigger('click');
    await flushPromises();

    tableApi.toggleRowSelection(itemC, true);
    await flushPromises();
    await wrapper.find('[data-testid="product-master-bulk-delete"]').trigger('click');
    await flushPromises();

    expect(api.deleteProductSpu.mock.calls.slice(3)).toEqual([[72], [74], [73]]);
    expect(api.deleteProductSpu.mock.calls.slice(3).flat()).toContain(74);
    expect(api.deleteProductSpu.mock.calls.slice(3).flat()).not.toContain(71);
  });
});
