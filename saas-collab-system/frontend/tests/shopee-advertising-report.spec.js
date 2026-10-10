import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchAdvertisingOverview: vi.fn(), fetchAdvertisingPerformance: vi.fn() }));
vi.mock('../src/api/advertising', () => api);
import ShopeeAdvertisingReport from '../src/components/ShopeeAdvertisingReport.vue';
const stubs = {
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' },
  'el-skeleton': { template: '<p>loading</p>' },
  'el-button': { emits: ['click'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<div><slot /></div>' },
  'el-select': { template: '<div><slot /></div>' }, 'el-option': true, 'el-date-picker': true,
  'el-table': true, 'el-table-column': true, 'el-pagination': true,
};
describe('Shopee persisted advertising report', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchAdvertisingOverview.mockResolvedValue({ success: true, data: { results: [], count: 0, stores: [] } });
    api.fetchAdvertisingPerformance.mockResolvedValue({ success: true, data: { results: [], count: 0, stores: [] } });
  });
  it('shows actionable empty state without sample spend', async () => {
    const wrapper = mount(ShopeeAdvertisingReport, { global: { stubs } });
    await flushPromises();
    expect(api.fetchAdvertisingOverview).toHaveBeenCalledWith({ kind: 'shop_daily', page: 1, page_size: 20 });
    expect(wrapper.text()).toContain('ADVERTISING 只读能力');
    expect(wrapper.text()).toContain('广告消耗不是账单扣费');
    expect(wrapper.text()).not.toContain('模拟');
  });
  it('defaults performance to campaign facts', async () => {
    mount(ShopeeAdvertisingReport, { props: { performance: true }, global: { stubs } });
    await flushPromises();
    expect(api.fetchAdvertisingPerformance).toHaveBeenCalledWith({ kind: 'campaign_daily', page: 1, page_size: 20 });
  });
  it('queries hourly and GMS period facts without offering keyword recommendations', async () => {
    const wrapper = mount(ShopeeAdvertisingReport, { global: { stubs } });
    await flushPromises();
    expect(wrapper.vm.kinds.map(item => item.value)).not.toContain('recommended_keyword');
    wrapper.vm.kind = 'campaign_hourly';
    wrapper.vm.period = ['2026-09-15', '2026-09-30'];
    await wrapper.vm.search();
    await flushPromises();
    expect(api.fetchAdvertisingOverview).toHaveBeenLastCalledWith(expect.objectContaining({
      kind: 'campaign_hourly', period_start: '2026-09-15', period_end: '2026-09-30'
    }));
    wrapper.vm.kind = 'gms_item';
    await wrapper.vm.search();
    await flushPromises();
    expect(wrapper.text()).toContain('整个采集区间的汇总');
    expect(wrapper.vm.columns.map(item => item.key)).toEqual(expect.arrayContaining(['item_id', 'period_start', 'period_end']));
    expect(api.fetchAdvertisingOverview).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'gms_item', period_start: '2026-09-15' }));
  });
  it('keeps failures visible and allows a query retry', async () => {
    api.fetchAdvertisingOverview.mockResolvedValueOnce({ success: false, message: '读取失败' });
    const wrapper = mount(ShopeeAdvertisingReport, { global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('读取失败');
    expect(wrapper.text()).not.toContain('暂无符合条件');
    await wrapper.get('button').trigger('click');
    await flushPromises();
    expect(api.fetchAdvertisingOverview).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain('暂无符合条件');
  });
  it('shows shop hourly with site hour and shop ROAS, separate from campaign reports', async () => {
    const wrapper = mount(ShopeeAdvertisingReport, { global: { stubs } });
    await flushPromises();
    expect(wrapper.vm.kinds).toContainEqual({ value: 'shop_hourly', label: '店铺整体小时报表' });
    wrapper.vm.kind = 'shop_hourly';
    wrapper.vm.period = ['2026-09-15', '2026-09-30'];
    await wrapper.vm.search();
    await flushPromises();
    expect(api.fetchAdvertisingOverview).toHaveBeenLastCalledWith(expect.objectContaining({
      kind: 'shop_hourly', period_start: '2026-09-15', period_end: '2026-09-30'
    }));
    expect(wrapper.vm.isDaily).toBe(true);
    expect(wrapper.vm.columns.map(item => item.key)).toEqual(expect.arrayContaining(['hour', 'direct_roas', 'broad_roas']));
    expect(wrapper.vm.columns.map(item => item.key)).not.toContain('direct_roi');
    expect(wrapper.text()).toContain('日报与小时报表不重复汇总');
  });
});
