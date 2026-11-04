import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi, afterEach } from 'vitest';
import ElementPlus from 'element-plus';
import Drilldown from '../src/components/TikTokGmvCampaignDrilldown.vue';
import { fetchTikTokDailySpend } from '../src/api/advertising';

vi.mock('../src/api/advertising', () => ({ fetchTikTokDailySpend: vi.fn() }));
let wrapper;
afterEach(() => { wrapper?.unmount(); vi.resetAllMocks(); });
function setup() {
  wrapper = mount(Drilldown, { props: { subjects: [{ store_id: 23, store_code: 'TK1PH' }],
    dateFrom: '2026-11-01', dateTo: '2026-11-02', advertiserId: '100' }, global: { plugins: [ElementPlus] } });
}
const campaign = { campaign_id: '300', campaign_type: 'unknown', campaign_name: null,
  store_code: 'TK1PH', advertiser_id: '100', currency: 'USD', timezone: 'Asia/Manila',
  cost: '10', gross_revenue: '30', orders: 2, roi: '3', cost_per_order: '5',
  covered_days: 1, expected_days: 2, days: [{ date: '2026-11-01', cost: '10', snapshot_id: 9 }] };
const result = { success: true, data: { campaigns: [campaign], warnings: [] } };

describe('stored GMV campaign drilldown', () => {
  it('queries scoped stored data and opens detail without another request', async () => {
    fetchTikTokDailySpend.mockResolvedValue(result);
    setup();
    await wrapper.vm.openStore(23);
    await flushPromises();
    expect(fetchTikTokDailySpend).toHaveBeenCalledWith({ report_type: 'gmv_max_campaigns', store_id: 23,
      date_from: '2026-11-01', date_to: '2026-11-02', advertiser_id: '100' });
    expect(wrapper.text()).toContain('名称未知');
    await wrapper.findAllComponents({ name: 'ElButton' }).find(b => b.text() === '查看详情').trigger('click');
    expect(wrapper.text()).toContain('计划详情：300');
    expect(wrapper.text()).toContain('账户快照覆盖 1/2 天');
    expect(fetchTikTokDailySpend).toHaveBeenCalledTimes(1);
    wrapper.findAllComponents({ name: 'ElSelect' })[1].vm.$emit('update:modelValue', 'product');
    await flushPromises();
    expect(wrapper.find('.campaign-detail').exists()).toBe(false);
    expect(wrapper.findComponent({ name: 'ElTable' }).props('data')).toEqual([]);
  });

  it('discards a stale response when the dates change', async () => {
    let resolve;
    fetchTikTokDailySpend.mockReturnValue(new Promise(r => { resolve = r; }));
    setup();
    const request = wrapper.vm.openStore(23);
    await wrapper.setProps({ dateFrom: '2026-10-30' });
    resolve(result);
    await request;
    expect(wrapper.findComponent({ name: 'ElTable' }).props('data')).toEqual([]);
  });

  it('does not turn timeout into zero data', async () => {
    fetchTikTokDailySpend.mockRejectedValue({ code: 'ECONNABORTED' });
    setup();
    await wrapper.vm.openStore(23);
    await flushPromises();
    expect(wrapper.text()).toContain('计划查询超时');
  });
});
