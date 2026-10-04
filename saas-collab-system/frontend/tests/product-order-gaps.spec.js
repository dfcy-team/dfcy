import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ requestApi: vi.fn(), updateSyncJob: vi.fn() }));
const messages = vi.hoisted(() => ({ success: vi.fn() }));
vi.mock('../src/api/request', () => ({ requestApi: api.requestApi }));
vi.mock('../src/api/integrations', () => ({ updateSyncJob: api.updateSyncJob }));
vi.mock('element-plus', async (importOriginal) => ({ ...(await importOriginal()), ElMessage: messages }));

import ProductOrderGaps from '../src/components/ProductOrderGaps.vue';
import SyncScheduleSettings from '../src/components/SyncScheduleSettings.vue';

beforeEach(() => {
  vi.clearAllMocks();
  messages.success.mockClear();
  api.requestApi.mockResolvedValue({ success: true, data: {
    times: [],
    summary: { source_rows: 12, unique_pairs: 5, linked_pairs: 3, missing_pairs: 2, missing_product_ids: 1, missing_variant_pairs: 1, conflict_pairs: 1, invalid_pairs: 0, zero_variant_pairs: 0, watermark: '2026-10-04T00:00:00Z' },
    samples: [{ product_id: 'P1', variant_id: 'V1', reason: 'identity_conflict', item_rows: 2 }],
    policy: 'catalog_and_order_missing', notice: '部分平台商品可能不可用。',
  } });
  api.updateSyncJob.mockResolvedValue({ success: true });
});

const job = (overrides = {}) => ({ id: 7, platform: 'shopee', resource_type: 'platform_product', product_full_sync: true, schedule_type: 'manual', ...overrides });
const nativeStubs = {
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-select': { props: ['modelValue'], emits: ['update:modelValue'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-alert': { props: ['title'], template: '<div role="alert">{{ title }}</div>' },
  'el-table': { props: ['data'], template: '<table>{{ JSON.stringify(data) }}<slot /></table>' },
  'el-table-column': { props: ['prop', 'label'], template: '<span>{{ label }}</span>' },
};

describe('Shopee 商品订单补齐策略', () => {
  it('shows all three policies only for Shopee platform product jobs and retains the selected value on save', async () => {
    const wrapper = mount(SyncScheduleSettings, { props: { job: job(), canManage: true }, global: { stubs: nativeStubs } });
    const policySelect = () => wrapper.findAll('select').find(select => select.text().includes('仅常规商品同步'));
    expect(policySelect().exists()).toBe(true);
    expect(policySelect().text()).toContain('仅常规商品同步');
    expect(wrapper.vm.form.product_order_backfill).toBe('catalog_and_order_missing');
    await policySelect().setValue('order_missing_only');
    expect(wrapper.vm.isMissingOrdersOnly).toBe(true);
    expect(wrapper.text()).toContain('本任务环境内、本店全部已落库订单');
    expect(wrapper.findAll('select').some(select => select.element.options.length === 2)).toBe(false);
    await wrapper.vm.preview();
    await wrapper.vm.save();
    expect(api.requestApi).toHaveBeenCalledWith(expect.objectContaining({ data: expect.objectContaining({ product_order_backfill: 'order_missing_only' }) }));
    expect(api.updateSyncJob).toHaveBeenCalledWith(7, expect.objectContaining({ product_order_backfill: 'order_missing_only' }));
    expect(api.updateSyncJob.mock.calls[0][1]).not.toHaveProperty('is_enabled');
    await wrapper.setProps({ job: job({ platform: 'lazada' }) });
    expect(wrapper.findAll('select').some(select => select.text().includes('仅常规商品同步'))).toBe(false);
    wrapper.unmount();
  });

  it('does not show policy controls for non-product jobs', async () => {
    const wrapper = mount(SyncScheduleSettings, { props: { job: job({ resource_type: 'sales_order' }), canManage: true }, global: { stubs: nativeStubs } });
    expect(wrapper.findAll('select').some(select => select.text().includes('仅常规商品同步'))).toBe(false);
    expect(wrapper.vm.form).not.toHaveProperty('product_order_backfill');
    wrapper.unmount();
  });
});

describe('商品关联缺口只读预览', () => {
  it('does not query on load, then manually loads summary and bounded samples', async () => {
    const wrapper = mount(ProductOrderGaps, { props: { job: job({ order_product_reconciliation: { before: { missing_pairs: 4 }, after: { missing_pairs: 2 }, attempted_products: 3, unavailable_products: 1, identity_conflicts: 1 } }), canView: true }, global: { stubs: nativeStubs } });
    expect(api.requestApi).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('补采阶段前缺少关联 4 对，补采后 2 对');
    await wrapper.find('button').trigger('click');
    await flushPromises();
    expect(api.requestApi).toHaveBeenCalledWith({ method: 'get', url: '/api/internal/integrations/sync-jobs/7/product-gaps/', timeout: 60000 });
    expect(wrapper.text()).toContain('源订单 12 行');
    expect(wrapper.text()).toContain('冲突 1 对');
    expect(wrapper.text()).toContain('identity_conflict');
    expect(wrapper.text()).toContain('P1');
    expect(wrapper.text()).toContain('最多展示 20 条样本');
    wrapper.unmount();
  });

  it('hides the preview control and blocks requests without integrations.view', async () => {
    const wrapper = mount(ProductOrderGaps, { props: { job: job(), canView: false }, global: { stubs: nativeStubs } });
    expect(wrapper.find('button').exists()).toBe(false);
    await wrapper.vm.loadPreview();
    expect(api.requestApi).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('guards duplicate loading and displays server errors', async () => {
    let finish;
    api.requestApi.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(ProductOrderGaps, { props: { job: job(), canView: true }, global: { stubs: nativeStubs } });
    await wrapper.find('button').trigger('click');
    await wrapper.find('button').trigger('click');
    expect(api.requestApi).toHaveBeenCalledTimes(1);
    finish({ success: false, message: '服务暂不可用' });
    await flushPromises();
    expect(wrapper.find('[role="alert"]').text()).toContain('服务暂不可用');
    wrapper.unmount();
  });

  it('clears an old preview when switching to another job and ignores its late response', async () => {
    let finish;
    api.requestApi.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(ProductOrderGaps, { props: { job: job(), canView: true }, global: { stubs: nativeStubs } });
    const pendingRequest = wrapper.vm.loadPreview();
    expect(api.requestApi).toHaveBeenCalledTimes(1);
    await wrapper.setProps({ job: job({ id: 8 }) });
    finish({ success: true, data: { summary: { source_rows: 999 }, samples: [] } });
    await pendingRequest;
    await flushPromises();
    expect(wrapper.text()).not.toContain('999');
    expect(wrapper.vm.preview).toBeNull();
    wrapper.unmount();
  });
});
