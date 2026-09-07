import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ElMessage, ElMessageBox } from 'element-plus';

const state = vi.hoisted(() => ({
  permissions: new Set(['integrations.product_mapping.view', 'integrations.product_mapping.manage', 'integrations.product_mapping.confirm']),
}));
const api = vi.hoisted(() => ({
  confirmProductMapping: vi.fn(),
  createProductMapping: vi.fn(),
  deactivateProductMapping: vi.fn(),
  fetchProductMappingOptions: vi.fn(),
  fetchProductMappings: vi.fn(),
  suggestProductMapping: vi.fn(),
}));

vi.mock('../src/api/integrations', () => api);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (...codes) => codes.some((code) => state.permissions.has(code)),
    isModuleEnabled: () => true,
  }),
}));

import ProductMappingPanel from '../src/components/ProductMappingPanel.vue';

const stubs = {
  'el-drawer': {
    props: { modelValue: Boolean, title: String },
    emits: ['update:modelValue', 'closed'],
    template: '<aside v-if="modelValue" class="drawer"><h2>{{ title }}</h2><slot /></aside>',
  },
  'el-alert': { props: { title: String }, template: '<div class="alert">{{ title }}<slot /></div>' },
  'el-button': {
    props: { disabled: Boolean, loading: Boolean, type: String },
    emits: ['click'],
    template: '<button :disabled="disabled" :data-loading="loading" @click="$emit(\'click\')"><slot /></button>',
  },
  'el-tag': { template: '<span class="tag"><slot /></span>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: { label: String }, template: '<label>{{ label }}<slot /></label>' },
  'el-select': {
    props: { modelValue: [String, Number], disabled: Boolean },
    emits: ['update:modelValue'],
    template: '<select class="sku-select" :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  },
  'el-input': {
    props: { modelValue: String },
    emits: ['update:modelValue'],
    template: '<input class="search-input" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-option': { props: { label: String, value: [String, Number] }, template: '<option :value="value">{{ label }}</option>' },
  'el-input-number': {
    props: { modelValue: Number, disabled: Boolean },
    emits: ['update:modelValue'],
    template: '<input class="confidence-input" type="number" :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
  },
  'el-descriptions': { template: '<dl><slot /></dl>' },
  'el-descriptions-item': { props: { label: String }, template: '<div><dt>{{ label }}</dt><dd><slot /></dd></div>' },
  'el-table': { template: '<div><slot /></div>' },
  'el-table-column': { template: '<div />' },
  'el-pagination': { template: '<div />' },
};

const detail = {
  id: 701,
  platform: 'shopee',
  platform_name: 'Shopee',
  store_id: 1,
  store_name: '新加坡示例店铺',
  platform_product_id: 'P-001',
  platform_variant_id: 'V-001',
  platform_sku: 'P-SKU-001',
  title: '演示商品',
  variant: '蓝色',
};

function response(mapping = { id: 401, status: 'suggested', sku_id: 11, sku_code: 'SKU-001', confidence: 92 }, detailOverride = detail) {
  return {
    success: true,
    code: 'OK',
    message: 'ok',
    data: {
      platform_details: [{ ...detailOverride, mapping }],
      mapping,
      skus: [
        { id: 11, sku_code: 'SKU-001', product_name: '演示商品' },
        { id: 12, sku_code: 'SKU-002', product_name: '另一个商品' },
      ],
    },
  };
}

async function mountPanel(mapping, detailOverride = detail) {
  api.fetchProductMappingOptions.mockResolvedValue(response(mapping, detailOverride));
  api.fetchProductMappings.mockResolvedValue({ success: true, data: { results: [] } });
  const wrapper = mount(ProductMappingPanel, {
    props: { modelValue: true, row: { ...detailOverride, mapping } },
    global: { stubs },
  });
  await flushPromises();
  return wrapper;
}

async function mountStandalone({ initialStatus = 'unlinked', initialVariantId = 'legacy-variant-001', initialStoreId = 1 } = {}) {
  api.fetchProductMappings.mockResolvedValue({
    success: true,
    data: {
      count: 1,
      results: [{
        id: 406,
        platform: 'shopee',
        store_id: initialStoreId,
        platform_variant_id: initialVariantId,
        status: 'conflict',
        sku_id: 16,
        sku_code: 'SKU-006',
      }],
    },
  });
  const wrapper = mount(ProductMappingPanel, {
    props: { standalone: true, initialStatus, initialVariantId, initialStoreId },
    global: { stubs },
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  state.permissions = new Set(['integrations.product_mapping.view', 'integrations.product_mapping.manage', 'integrations.product_mapping.confirm']);
  vi.clearAllMocks();
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(true);
  vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined);
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined);
  vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined);
  api.suggestProductMapping.mockResolvedValue({ success: true, data: { id: 402, status: 'suggested', sku_id: 12, sku_code: 'SKU-002', confidence: 88 } });
  api.confirmProductMapping.mockResolvedValue({ success: true, data: { id: 401, status: 'mapped', sku_id: 12, sku_code: 'SKU-002', confidence: 100, manually_confirmed: true } });
  api.deactivateProductMapping.mockResolvedValue({ success: true, data: { id: 401, status: 'inactive' } });
});

describe('平台商品明细中的 SKU 映射面板', () => {
  it('从本地 SKU 选择建议并提交，不要求输入数字 ID', async () => {
    const wrapper = await mountPanel({ id: 402, status: 'unmapped' });
    wrapper.vm.selectedSkuId = 12;
    await wrapper.vm.$nextTick();
    const button = wrapper.findAll('button').find((item) => item.text() === '登记建议');
    expect(button.exists()).toBe(true);
    await button.trigger('click');
    await flushPromises();
    expect(api.suggestProductMapping).toHaveBeenCalledWith(402, expect.objectContaining({ sku_id: 12 }));
  });

  it('把待确认建议提交为人工确认映射', async () => {
    const wrapper = await mountPanel({ id: 401, status: 'suggested', sku_id: 11, sku_code: 'SKU-001' });
    wrapper.vm.selectedSkuId = 12;
    await wrapper.vm.$nextTick();
    await wrapper.findAll('button').find((item) => item.text() === '人工确认').trigger('click');
    await flushPromises();
    expect(api.confirmProductMapping).toHaveBeenCalledWith(401, expect.objectContaining({ sku_id: 12, manually_confirmed: true }));
  });

  it('冲突状态确认新 SKU 时携带旧 SKU 乐观锁并明确替换', async () => {
    const wrapper = await mountPanel(
      { id: 401, status: 'conflict', sku_id: 11, sku_code: 'SKU-001', confidence: 68 },
      { ...detail, internal_sku_id: 11, internal_sku_code: 'SKU-001' },
    );
    wrapper.vm.selectedSkuId = 12;
    await wrapper.vm.$nextTick();
    await wrapper.findAll('button').find((item) => item.text() === '人工确认').trigger('click');
    await flushPromises();
    expect(api.confirmProductMapping).toHaveBeenCalledWith(401, expect.objectContaining({
      sku_id: 12,
      replace_existing: true,
      expected_internal_sku_id: 11,
      manually_confirmed: true,
    }));
  });

  it('待确认状态允许有管理权限的人员调整建议', async () => {
    const wrapper = await mountPanel({ id: 401, status: 'suggested', sku_id: 11, sku_code: 'SKU-001' });
    wrapper.vm.selectedSkuId = 12;
    await wrapper.vm.$nextTick();
    const button = wrapper.findAll('button').find((item) => item.text() === '调整建议');
    expect(button.exists()).toBe(true);
    await button.trigger('click');
    await flushPromises();
    expect(api.suggestProductMapping).toHaveBeenCalledWith(401, expect.objectContaining({ sku_id: 12 }));
  });

  it('停用映射后保留历史状态', async () => {
    const wrapper = await mountPanel({ id: 401, status: 'mapped', sku_id: 11, sku_code: 'SKU-001' });
    await wrapper.findAll('button').find((item) => item.text() === '停用映射').trigger('click');
    await flushPromises();
    expect(api.deactivateProductMapping).toHaveBeenCalledWith(401);
    expect(ElMessage.success).toHaveBeenCalledWith('商品映射已停用。');
  });

  it('操作失败后解除 loading 并显示刷新入口', async () => {
    api.suggestProductMapping.mockRejectedValueOnce(new Error('网络暂不可用'));
    const wrapper = await mountPanel({ id: 402, status: 'unmapped' });
    wrapper.vm.selectedSkuId = 12;
    await wrapper.vm.$nextTick();
    await wrapper.findAll('button').find((item) => item.text() === '登记建议').trigger('click');
    await flushPromises();
    expect(wrapper.vm.saving).toBe(false);
    expect(wrapper.text()).toContain('网络暂不可用');
    expect(wrapper.text()).toContain('刷新状态');
  });

  it('只有查看权限时隐藏全部写入按钮', async () => {
    state.permissions = new Set(['integrations.product_mapping.view']);
    const wrapper = await mountPanel({ id: 401, status: 'suggested' });
    expect(wrapper.findAll('button').filter((item) => /新建映射|登记建议|人工确认|停用映射/.test(item.text()))).toHaveLength(0);
    expect(wrapper.text()).toContain('只读');
  });

  it('未归集历史按服务端搜索、店铺和变体上下文读取', async () => {
    const wrapper = await mountStandalone();
    expect(api.fetchProductMappings).toHaveBeenLastCalledWith(expect.objectContaining({
      unlinked: true,
      search: undefined,
      store_id: 1,
      platform_variant_id: 'legacy-variant-001',
    }));
    wrapper.vm.listFilters.search = 'legacy';
    await wrapper.vm.loadStandalone();
    await flushPromises();
    expect(api.fetchProductMappings).toHaveBeenLastCalledWith(expect.objectContaining({
      unlinked: true,
      search: 'legacy',
      store_id: 1,
      platform_variant_id: 'legacy-variant-001',
    }));
  });

  it('映射 options 没有商品明细时清空上下文并禁止继续写入', async () => {
    api.fetchProductMappingOptions.mockResolvedValue({
      success: true,
      code: 'OK',
      message: 'ok',
      data: { count: 0, platform_details: [], skus: [] },
    });
    const wrapper = mount(ProductMappingPanel, {
      props: { modelValue: true, row: { ...detail, mapping: null } },
      global: { stubs },
    });
    await flushPromises();

    expect(wrapper.vm.detail).toBe(null);
    expect(wrapper.text()).toContain('未获得该商品的映射操作上下文，请检查店铺平台关联及数据权限');
    expect(wrapper.findAll('button').filter((item) => /新建映射|登记建议|人工确认|停用映射/.test(item.text()))).toHaveLength(0);
    expect(api.createProductMapping).not.toHaveBeenCalled();
  });
});
