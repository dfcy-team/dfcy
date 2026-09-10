import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const productsApi = vi.hoisted(() => ({
  bulkUpdateProductSpus: vi.fn(),
  createProductSku: vi.fn(),
  createProductSkuBatch: vi.fn(),
  createProductSpu: vi.fn(),
  fetchProductAttributes: vi.fn(),
  fetchProductCategories: vi.fn(),
  fetchProductCategoryBackgroundColors: vi.fn(),
  fetchProductColors: vi.fn(),
  fetchProductMasterList: vi.fn(),
  updateProductSpu: vi.fn(),
}));

vi.mock('../src/api/products', () => productsApi);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => true }),
}));

import ProductMasterList from '../src/views/products/ProductMasterList.vue';

const categoryRows = [
  { id: 1, level: 1, code: '1', name: '家纺布艺', is_active: true },
  { id: 2, level: 2, parent: 1, code: '01', name: '床上用品', is_active: true },
  { id: 3, level: 3, parent: 2, code: '01', name: '床笠', is_active: true },
];
const attributeRows = [
  { id: 11, code: '2', name: '春季', is_active: true },
  { id: 12, code: '3', name: '停用属性', is_active: false },
];

const collection = (results = []) => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: { count: results.length, results, api_status: 'connected' },
});
const stubs = {
  'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}</div>' },
  'el-button': {
    props: ['disabled', 'loading'],
    emits: ['click'],
    template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
  'el-dialog': {
    props: ['modelValue'],
    template: '<div v-if="modelValue" class="dialog-stub"><slot /><slot name="footer" /></div>',
  },
  'el-empty': { template: '<div><slot /></div>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': {
    props: ['label'],
    template: '<div class="form-item-stub"><label>{{ label }}</label><slot /></div>',
  },
  'el-input': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-option': {
    props: ['label', 'value'],
    template: '<option :value="value">{{ label }}</option>',
  },
  'el-pagination': { template: '<nav />' },
  'el-popover': {
    props: ['visible'],
    template: '<div v-if="visible"><slot name="reference" /><slot /></div>',
  },
  'el-select': {
    props: ['modelValue', 'disabled', 'loading'],
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  },
  'el-table': { template: '<div class="table-stub"><slot /></div>' },
  'el-table-column': true,
  'el-tag': { template: '<span><slot /></span>' },
  'el-tree': { template: '<div class="tree-stub"><slot /></div>' },
  'el-tree-select': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'router-link': { props: ['to'], template: '<a :href="to"><slot /></a>' },
};

function setupApiMocks() {
  productsApi.fetchProductCategories.mockResolvedValue(collection(categoryRows));
  productsApi.fetchProductCategoryBackgroundColors.mockResolvedValue(collection([]));
  productsApi.fetchProductColors.mockResolvedValue(collection([]));
  productsApi.fetchProductAttributes.mockResolvedValue(collection(attributeRows));
  productsApi.fetchProductMasterList.mockResolvedValue(collection([]));
  productsApi.createProductSpu.mockResolvedValue({
    success: true,
    code: 'OK',
    message: '商品已创建',
    data: { id: 101, spu_code: '1010102001' },
  });
}

async function mountPage() {
  const wrapper = mount(ProductMasterList, { global: { stubs } });
  await flushPromises();
  return wrapper;
}

describe('商品主数据属性编码创建流程', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApiMocks();
  });

  it('打开创建商品时刷新属性字典，并把选中的启用属性编码提交到兼容字段', async () => {
    const wrapper = await mountPage();

    expect(productsApi.fetchProductAttributes).toHaveBeenCalledWith({ page: 1, page_size: 500 });
    const initialAttributeCalls = productsApi.fetchProductAttributes.mock.calls.length;
    const createButton = wrapper.findAll('button').find((button) => button.text() === '创建商品');
    await createButton.trigger('click');
    await flushPromises();

    expect(productsApi.fetchProductAttributes).toHaveBeenCalledTimes(initialAttributeCalls + 1);
    expect(wrapper.text()).toContain('属性编码');
    expect(wrapper.text()).toContain('2 春季');
    expect(wrapper.text()).not.toContain('3 停用属性');

    wrapper.vm.createForm.product_name = '春季床笠';
    wrapper.vm.createForm.category_node = 3;
    await wrapper.get('[data-testid="product-attribute-code"]').setValue('2');
    await wrapper.vm.saveProduct();
    await flushPromises();

    expect(productsApi.createProductSpu).toHaveBeenCalledTimes(1);
    expect(productsApi.createProductSpu.mock.calls[0][0]).toMatchObject({
      product_name: '春季床笠',
      category_node: 3,
      season_code: '2',
      product_type: 'standard',
    });
  });

  it('把清空属性编码归一为 0，并阻止提交不在启用字典中的编码', async () => {
    const wrapper = await mountPage();
    await wrapper.vm.openCreate();
    await flushPromises();
    wrapper.vm.createForm.product_name = '默认属性床笠';
    wrapper.vm.createForm.category_node = 3;
    wrapper.vm.createForm.season_code = '';
    await wrapper.vm.saveProduct();
    await flushPromises();

    expect(productsApi.createProductSpu).toHaveBeenCalledTimes(1);
    expect(productsApi.createProductSpu.mock.calls[0][0].season_code).toBe('0');

    productsApi.createProductSpu.mockClear();
    wrapper.vm.createForm.product_name = '无效属性床笠';
    wrapper.vm.createForm.category_node = 3;
    wrapper.vm.createForm.season_code = '8';
    await wrapper.vm.saveProduct();

    expect(productsApi.createProductSpu).not.toHaveBeenCalled();
  });
});
