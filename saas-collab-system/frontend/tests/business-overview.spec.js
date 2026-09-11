import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchBusinessOverview: vi.fn(), fetchBusinessFilters: vi.fn() }));
vi.mock('../src/api/analytics', () => api);
import BusinessOverview from '../src/views/analytics/BusinessOverview.vue';

const group = (currency, count, cancelled) => ({ currency, metrics: [
  { code: 'order_count', value: count, unit: 'orders' },
  { code: 'cancelled_order_count', value: cancelled, unit: 'orders' },
  { code: 'gross_sales', value: '1234.50', unit: currency }
] });
const render = () => mount(BusinessOverview, { global: { directives: { loading: () => {} }, stubs: {
  SalesOverviewPanel: { props: ['currencyCode'], methods: { color: () => 'blue', toggle: () => {} }, template: '<section :data-currency="currencyCode"><slot name="metrics" :selected="[]" :toggle="toggle" :color="color" /></section>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<label><slot /></label>' },
  'el-select': true, 'el-option': true, 'el-date-picker': true,
  'el-button': { template: '<button><slot /></button>' }, 'el-tag': { template: '<span><slot /></span>' },
  'el-table': true, 'el-table-column': true,
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' }
} } });
beforeEach(() => {
  vi.clearAllMocks();
  api.fetchBusinessFilters.mockResolvedValue({ success: true, data: { platforms: ['shopee','tiktok'], stores: [{id:1,platform:'shopee'}, {id:2,platform:'tiktok'}] } });
  api.fetchBusinessOverview.mockResolvedValue({ success: true, data: { api_status:'connected', currency_groups:[group('PHP',100,5),group('THB',0,0)], results:[], count:0 } });
});
describe('经营总览', () => {
  it('isolates currency and derives cancellation rate without inventing missing metrics', async () => {
    const wrapper = render(); await flushPromises();
    expect(wrapper.findAll('[data-currency]')).toHaveLength(2);
    expect(wrapper.find('[data-currency=PHP]').text()).toContain('5.00%');
    expect(wrapper.find('[data-currency=THB]').text()).toContain('取消率—');
    expect(wrapper.find('[data-currency=PHP]').text()).toContain('1,234.50');
    expect(wrapper.text()).not.toContain('指标编码');
    wrapper.unmount();
  });
  it('supports platform/store multi-select, prunes incompatible stores and applies only on query', async () => {
    const wrapper = render(); await flushPromises();
    wrapper.vm.query.platforms = ['shopee']; wrapper.vm.query.store_ids = [1,2]; wrapper.vm.pruneStores();
    expect(wrapper.vm.query.store_ids).toEqual([1]);
    expect(wrapper.vm.pendingFilters).toBe(true);
    expect(api.fetchBusinessOverview).toHaveBeenCalledTimes(1);
    await wrapper.vm.search();
    expect(api.fetchBusinessOverview).toHaveBeenLastCalledWith(expect.objectContaining({ platforms:'shopee',store_ids:'1' }));
    expect(wrapper.vm.pendingFilters).toBe(false);
    wrapper.unmount();
  });
  it('clears stale data on failure and refuses mock fallback', async () => {
    const wrapper = render(); await flushPromises();
    api.fetchBusinessOverview.mockResolvedValue({success:true,data:{api_status:'fallback',currency_groups:[group('PHP',999,1)]}});
    await wrapper.vm.search();
    expect(wrapper.find('[data-currency]').exists()).toBe(false);
    expect(wrapper.text()).toContain('不使用模拟数据');
    wrapper.unmount();
  });
  it('keeps latest request result when responses arrive out of order', async () => {
    const wrapper = render(); await flushPromises();
    let resolveOld;
    api.fetchBusinessOverview.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const first = wrapper.vm.search();
    api.fetchBusinessOverview.mockResolvedValueOnce({success:true,data:{api_status:'connected',currency_groups:[group('THB',2,0)]}});
    await wrapper.vm.search();
    resolveOld({success:true,data:{api_status:'connected',currency_groups:[group('PHP',999,0)]}});
    await first; await flushPromises();
    expect(wrapper.find('[data-currency=PHP]').exists()).toBe(false);
    expect(wrapper.find('[data-currency=THB]').exists()).toBe(true);
    wrapper.unmount();
  });
});
