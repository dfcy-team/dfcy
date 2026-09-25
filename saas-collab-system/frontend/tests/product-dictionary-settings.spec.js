import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import ProductDictionarySettings from '../src/views/products/ProductDictionarySettings.vue';
import { invalidateProductDictionaryCache } from '../src/utils/productDictionaryCache';

const productApi = vi.hoisted(() => ({
  createProductAttribute: vi.fn(),
  createProductCategory: vi.fn(),
  createProductColor: vi.fn(),
  deleteProductAttribute: vi.fn(),
  deleteProductCategory: vi.fn(),
  deleteProductColor: vi.fn(),
  fetchProductAttributes: vi.fn(),
  fetchProductCategories: vi.fn(),
  fetchProductColors: vi.fn(),
  updateProductAttribute: vi.fn(),
  updateProductAttributes: vi.fn(),
  updateProductCategory: vi.fn(),
  updateProductColor: vi.fn()
}));

const authState = vi.hoisted(() => ({ allowed: true }));
const elementPlus = vi.hoisted(() => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn()
  },
  ElMessageBox: {
    confirm: vi.fn()
  }
}));

vi.mock('../src/api/products', () => productApi);
vi.mock('../src/utils/productDictionaryCache', () => ({
  invalidateProductDictionaryCache: vi.fn()
}));
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (...codes) => authState.allowed && codes.length > 0
  })
}));
vi.mock('element-plus', async (importOriginal) => ({
  ...(await importOriginal()),
  ...elementPlus
}));

const success = (data = []) => ({ success: true, code: 'OK', message: 'success', data });
const categories = [
  { id: 1, level: 1, code: '1', name: '家居', parent: null, is_active: true },
  { id: 10, level: 2, code: '01', name: '卧室', parent: 1, is_active: true },
  { id: 11, level: 2, code: '02', name: '客厅', parent: 1, is_active: true },
  { id: 20, level: 3, code: '01', name: '床品', parent: 10, is_active: true, spec_dimensions: [{ code: 'size', name: '尺寸', values: ['10cm'] }] }
];

const stubs = {
  ElAlert: { props: ['title'], template: '<div class="alert-stub">{{ title }}</div>' },
  ElButton: {
    props: ['disabled', 'loading'],
    emits: ['click'],
    template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>'
  },
  ElDialog: {
    props: ['modelValue', 'title'],
    template: '<section v-if="modelValue" class="dialog-stub"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>'
  },
  ElEmpty: { props: ['description'], template: '<div class="empty-stub">{{ description }}</div>' },
  ElForm: { template: '<form @submit.prevent="$emit(\'submit\')"><slot /></form>' },
  ElFormItem: { props: ['label'], template: '<div class="form-item"><label>{{ label }}</label><slot /></div>' },
  ElInput: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />'
  },
  ElOption: { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  ElSelect: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>'
  },
  ElSwitch: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<button @click="$emit(\'update:modelValue\', !modelValue)">{{ modelValue ? \'启用\' : \'停用\' }}</button>'
  },
  ElTable: { props: ['data'], template: '<div class="table-stub"><slot /></div>' },
  ElTableColumn: { props: ['label'], template: '<div class="table-column-stub"><span>{{ label }}</span></div>' },
  ElTag: { template: '<span class="tag-stub"><slot /></span>' },
  ElTree: {
    props: ['data'],
    methods: { filter: vi.fn() },
    template: '<div class="tree-stub"><div v-for="item in data" :key="item.id" class="tree-item"><slot :data="item" /></div></div>'
  }
};

function mountPage(kind) {
  return mount(ProductDictionarySettings, {
    props: { kind },
    global: { stubs }
  });
}

describe('ProductDictionarySettings mounted kind matrix', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.allowed = true;
    elementPlus.ElMessageBox.confirm.mockResolvedValue('confirm');
    productApi.fetchProductCategories.mockResolvedValue(success(categories));
    productApi.fetchProductAttributes.mockResolvedValue(success([{ id: 5, code: '1', name: '季节', is_active: true }]));
    productApi.fetchProductColors.mockResolvedValue(success([{ id: 6, code: 'black', name: '黑色', is_active: true }]));
    productApi.createProductAttribute.mockResolvedValue(success({ id: 7, code: '2', name: '材质' }));
    productApi.createProductCategory.mockResolvedValue(success({ id: 8 }));
    productApi.createProductColor.mockResolvedValue(success({ id: 9 }));
    productApi.updateProductAttribute.mockResolvedValue(success({}));
    productApi.updateProductAttributes.mockResolvedValue(success({ category_id: 20, spec_dimensions: [] }));
    productApi.updateProductCategory.mockResolvedValue(success({}));
    productApi.updateProductColor.mockResolvedValue(success({}));
    productApi.deleteProductAttribute.mockResolvedValue(success({ deleted: true }));
    productApi.deleteProductCategory.mockResolvedValue(success({ deleted: true }));
    productApi.deleteProductColor.mockResolvedValue(success({ deleted: true }));
  });

  it.each([
    ['categories', '分类设置', '分类目录'],
    ['attributes', '属性设置', '商品属性字典'],
    ['colors', '颜色设置', '颜色编码字典'],
    ['specifications', '规格设置', '分类规格维度']
  ])('renders the %s page through the router kind prop', async (kind, title, contentTitle) => {
    const wrapper = mountPage(kind);
    await flushPromises();

    expect(wrapper.text()).toContain(title);
    expect(wrapper.text()).toContain(contentTitle);
    expect(wrapper.find('[data-testid="dictionary-refresh"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="dictionary-export"]').exists()).toBe(true);
    if (kind === 'categories') expect(wrapper.find('[data-testid="category-tree"]').exists()).toBe(true);
    if (kind === 'specifications') expect(wrapper.find('[data-testid="dictionary-create"]').exists()).toBe(false);
  });

  it.each([
    ['categories', '分类设置_'],
    ['attributes', '属性设置_'],
    ['colors', '颜色设置_'],
    ['specifications', '规格设置_']
  ])('exports the %s dictionary as a UTF-8 CSV', async (kind, filenamePrefix) => {
    if (!URL.createObjectURL) Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn() });
    if (!URL.revokeObjectURL) Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:dictionary-export');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    let downloadedFilename = '';
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function captureDownload() {
      downloadedFilename = this.download;
    });
    const wrapper = mountPage(kind);
    await flushPromises();

    await wrapper.find('[data-testid="dictionary-export"]').trigger('click');

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(click).toHaveBeenCalledTimes(1);
    expect(downloadedFilename).toMatch(new RegExp(`^${filenamePrefix}\\d{4}-\\d{2}-\\d{2}\\.csv$`));
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:dictionary-export');
    expect(elementPlus.ElMessage.success).toHaveBeenCalledWith(expect.stringContaining('已导出'));

    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
    click.mockRestore();
  });

  it('keeps the old mode prop compatible with the category page', async () => {
    const wrapper = mount(ProductDictionarySettings, {
      props: { mode: 'category' },
      global: { stubs }
    });
    await flushPromises();

    expect(wrapper.text()).toContain('分类设置');
    expect(productApi.fetchProductCategories).toHaveBeenCalled();
  });

  it('moves a category with only a parent PATCH payload', async () => {
    const wrapper = mountPage('categories');
    await flushPromises();

    wrapper.vm.openMove(categories[3]);
    wrapper.vm.form.parent = 11;
    await wrapper.vm.save();

    expect(productApi.updateProductCategory).toHaveBeenCalledWith(20, { parent: 11 });
    expect(productApi.updateProductCategory.mock.calls[0][1]).not.toHaveProperty('code');
    expect(productApi.updateProductCategory.mock.calls[0][1]).not.toHaveProperty('level');
  });

  it('filters the category table to the selected node and its descendants', async () => {
    const wrapper = mountPage('categories');
    await flushPromises();

    wrapper.vm.selectCategory(wrapper.vm.rows.find((item) => item.id === 10));
    expect(wrapper.vm.categoryDisplayRows.map((item) => item.id)).toEqual([10, 20]);
    wrapper.vm.selectCategory(null);
    expect(wrapper.vm.categoryDisplayRows).toHaveLength(categories.length);
  });

  it('does not let a stale category request overwrite the newer kind', async () => {
    let resolveCategories;
    productApi.fetchProductCategories.mockImplementationOnce(() => new Promise((resolve) => {
      resolveCategories = resolve;
    }));
    const wrapper = mountPage('categories');
    await Promise.resolve();

    await wrapper.setProps({ kind: 'colors' });
    await flushPromises();
    expect(wrapper.vm.rows.map((item) => item.code)).toEqual(['black']);

    resolveCategories(success(categories));
    await flushPromises();
    expect(wrapper.vm.rows.map((item) => item.code)).toEqual(['black']);
  });

  it('saves the standalone attribute and color dictionaries', async () => {
    const attributePage = mountPage('attributes');
    await flushPromises();
    attributePage.vm.openCreate();
    attributePage.vm.form.name = '材质';
    await attributePage.vm.save();
    expect(productApi.createProductAttribute).toHaveBeenCalledWith({ name: '材质', is_active: true });

    const colorPage = mountPage('colors');
    await flushPromises();
    colorPage.vm.openCreate();
    colorPage.vm.form.code = 'navy';
    colorPage.vm.form.name = '藏青';
    await colorPage.vm.save();
    expect(productApi.createProductColor).toHaveBeenCalledWith({ code: 'navy', name: '藏青', is_active: true });
    expect(invalidateProductDictionaryCache).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['attributes', '1', '材质', [{ id: 5, code: '1', name: '季节', is_active: true }, { id: 7, code: '2', name: '材质', is_active: true }]],
    ['colors', 'black', '藏青', [{ id: 6, code: 'black', name: '黑色', is_active: true }, { id: 8, code: 'navy', name: '藏青', is_active: true }]]
  ])('searches %s by code or name and clears the filter', async (kind, code, name, items) => {
    if (kind === 'attributes') productApi.fetchProductAttributes.mockResolvedValue(success(items));
    else productApi.fetchProductColors.mockResolvedValue(success(items));
    const wrapper = mountPage(kind);
    await flushPromises();
    const input = wrapper.find('[data-testid="dictionary-search"]');

    await input.setValue(code.toUpperCase());
    expect(wrapper.vm.displayRows.map((item) => item.code)).toEqual([code]);
    await input.setValue(name);
    expect(wrapper.vm.displayRows.map((item) => item.name)).toEqual([name]);
    await input.setValue('不存在');
    expect(wrapper.vm.displayRows).toEqual([]);
    expect(wrapper.vm.tableEmptyText).toBe('没有匹配的记录');
    await input.setValue('');
    expect(wrapper.vm.displayRows).toHaveLength(2);
  });

  it('preserves existing specification values when saving a category', async () => {
    const wrapper = mountPage('specifications');
    await flushPromises();

    wrapper.vm.edit(categories[3]);
    await wrapper.vm.save();

    expect(productApi.updateProductAttributes).toHaveBeenCalledWith(20, [
      { code: 'size', name: '尺寸', values: ['10cm'] }
    ]);
  });

  it('shows a category tree and switches the specification workspace by leaf selection', async () => {
    const wrapper = mountPage('specifications');
    await flushPromises();

    expect(wrapper.find('[data-testid="specification-tree"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="specification-filter"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="specification-guide"]').exists()).toBe(true);

    wrapper.vm.selectCategory(wrapper.vm.rows.find((item) => item.id === 10));
    expect(wrapper.find('[data-testid="specification-guide"]').exists()).toBe(true);

    wrapper.vm.selectCategory(wrapper.vm.rows.find((item) => item.id === 20));
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[data-testid="specification-detail"]').text()).toContain('01 床品');
    expect(wrapper.find('[data-testid="specification-dimensions"]').text()).toContain('尺寸');
    expect(wrapper.find('[data-testid="specification-edit"]').exists()).toBe(true);
  });

  it('searches specification dimensions and values while keeping matching ancestors visible', async () => {
    const wrapper = mountPage('specifications');
    await flushPromises();
    const input = wrapper.find('[data-testid="specification-filter"]');

    await input.setValue('10CM');
    expect(wrapper.vm.matchingSpecificationRows.map((item) => item.id)).toEqual([20]);
    expect(wrapper.vm.filterCategory('10CM', wrapper.vm.rows.find((item) => item.id === 1))).toBe(true);
    expect(wrapper.vm.filterCategory('10CM', wrapper.vm.rows.find((item) => item.id === 10))).toBe(true);
    expect(wrapper.vm.filterCategory('10CM', wrapper.vm.rows.find((item) => item.id === 20))).toBe(true);
    expect(wrapper.vm.filterCategory('10CM', wrapper.vm.rows.find((item) => item.id === 11))).toBe(false);

    await input.setValue('size');
    expect(wrapper.vm.matchingSpecificationRows.map((item) => item.id)).toEqual([20]);
    await input.setValue('未匹配');
    expect(wrapper.vm.matchingSpecificationRows).toEqual([]);
    await input.setValue('');
    expect(wrapper.vm.matchingSpecificationRows.map((item) => item.id)).toEqual([11, 20]);
  });

  it('sends the backend field name used by the category specification endpoint', () => {
    const source = fs.readFileSync(path.resolve(process.cwd(), 'src/api/products.js'), 'utf8');
    expect(source).toContain("method: 'put'");
    expect(source).toContain('data: { spec_dimensions }');
    expect(source).not.toContain('data: { attributes }');
  });
});
