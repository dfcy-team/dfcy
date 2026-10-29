import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MonthlySalesProgress from '../src/views/dashboard/MonthlySalesProgress.vue';

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  auth: {
    currentUser: { id: 7, user_type: 'internal' },
    isSuperuser: false,
    actionPermissionSet: new Set(['sales_management.view']),
    hasActionPermission(code) { return this.actionPermissionSet.has(code); },
  },
}));

const managedStores = [
  { id: 11, code: 'SHOP-11', name: '北区旗舰店', platform_store_name: 'Platform North' },
  { id: 12, code: 'SHOP-12', name: '', platform_store_name: 'Platform South' },
];

vi.mock('../src/api/salesManagement', () => ({ fetchMonthlySalesProgress: mocks.fetch }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => mocks.auth }));

describe('dashboard monthly growth', () => {
  beforeEach(() => {
    mocks.fetch.mockReset();
    mocks.auth.currentUser = { id: 7, user_type: 'internal' };
    mocks.auth.actionPermissionSet = new Set(['sales_management.view']);
  });

  it('shows daily up/down ratios without displaying sales amounts or quantities', async () => {
    mocks.fetch.mockResolvedValue({
      success: true,
      data: {
        month: '2026-10',
        through: '2026-10-02',
        previous_day: '2026-09-30',
        platforms: [{ id: 3, name: 'TikTok', code: 'tiktok' }],
        stores: managedStores,
        selected_store_id: null,
        currencies: [{
          currency: 'USD',
          previous: { amount: '100.00', quantity: 10 },
          daily: [
            { date: '2026-10-01', amount: '150.00', quantity: 20 },
            { date: '2026-10-02', amount: '75.00', quantity: 10 },
          ],
        }],
      },
    });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    expect(wrapper.text()).toContain('销售额日环比');
    expect(wrapper.text()).toContain('销量日环比');
    expect(wrapper.text()).toContain('↑50%');
    expect(wrapper.text()).toContain('↓50%');
    expect(wrapper.text()).not.toContain('150.00');
    expect(wrapper.text()).not.toContain('75.00');
    expect(wrapper.text()).not.toContain('20 件');
  });

  it('does not request data for a user without sales visibility', async () => {
    mocks.auth.actionPermissionSet = new Set();
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('暂无销售数据查看权限');
  });

  it('uses an increase icon without an infinite ratio when the previous day has no sales', async () => {
    mocks.fetch.mockResolvedValue({
      success: true,
      data: {
        month: '2026-10', through: '2026-10-01', previous_day: '2026-09-30',
        currencies: [{
          currency: 'PHP', previous: { amount: '0', quantity: 0 },
          daily: [{ date: '2026-10-01', amount: '300', quantity: 2 }],
        }],
      },
    });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    expect(wrapper.text()).toContain('↑ 新增');
    expect(wrapper.text()).not.toContain('Infinity');
    expect(wrapper.text()).not.toContain('300');
  });

  it('shows a decrease when only the previous month had sales', async () => {
    mocks.fetch.mockResolvedValue({
      success: true,
      data: {
        month: '2026-10', through: '2026-10-01', previous_day: '2026-09-30',
        currencies: [{ currency: 'MYR', previous: { amount: '13', quantity: 2 }, daily: [] }],
      },
    });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    expect(wrapper.text()).toContain('↓100%');
    expect(wrapper.text()).not.toContain('暂无销售订单');
  });

  it('keeps the store selector available for a no-sales result and defaults to all stores', async () => {
    mocks.fetch.mockResolvedValue({
      success: true,
      data: {
        month: '2026-10', through: '2026-10-01', previous_day: '2026-09-30',
        stores: managedStores, selected_store_id: null, currencies: [],
      },
    });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    const select = wrapper.get('#monthly-sales-store');
    expect(select.element.value).toBe('');
    expect(select.text()).toContain('全部可管理店铺');
    expect(select.text()).toContain('北区旗舰店');
    expect(select.text()).toContain('Platform North');
    expect(select.text()).toContain('Platform South');
    expect(wrapper.text()).toContain('本月可见范围内暂无销售及广告数据');
    expect(mocks.fetch).toHaveBeenCalledWith(null, null);
  });

  it('sends each selected store and ignores stale responses after rapid switches', async () => {
    let resolveStore;
    mocks.fetch
      .mockResolvedValueOnce({ success: true, data: {
        month: '2026-10', through: '2026-10-01', stores: managedStores, selected_store_id: null, currencies: [],
      } })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveStore = resolve; }))
      .mockResolvedValueOnce({ success: true, data: {
        month: '2026-10', through: '2026-10-01', stores: managedStores, selected_store_id: 12,
        currencies: [{ currency: 'USD', previous: { amount: '1', quantity: 1 }, daily: [] }],
      } });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    const select = wrapper.get('#monthly-sales-store');
    await select.setValue('11');
    await select.setValue('12');
    expect(mocks.fetch.mock.calls).toEqual([[null, null], [11, null], [12, null]]);
    await flushPromises();
    resolveStore({ success: true, data: {
      month: '2026-10', through: '2026-10-01', stores: managedStores, selected_store_id: 11,
      currencies: [{ currency: 'EUR', previous: { amount: '1', quantity: 1 }, daily: [] }],
    } });
    await flushPromises();
    expect(wrapper.get('#monthly-sales-store').element.value).toBe('12');
    expect(wrapper.text()).toContain('USD');
    expect(wrapper.text()).not.toContain('EUR');
  });

  it('clears old chart data on store errors and changes currency without refetching', async () => {
    mocks.fetch
      .mockResolvedValueOnce({ success: true, data: {
        month: '2026-10', through: '2026-10-01', stores: managedStores, selected_store_id: null,
        currencies: [
          { currency: 'USD', previous: { amount: '1', quantity: 1 }, daily: [] },
          { currency: 'EUR', previous: { amount: '1', quantity: 1 }, daily: [] },
        ],
      } })
      .mockResolvedValueOnce({ success: false, http_status: 500 });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    await wrapper.get('.currency-tabs button:nth-child(2)').trigger('click');
    expect(wrapper.text()).toContain('EUR');
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    await wrapper.get('#monthly-sales-store').setValue('11');
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain('销售数据暂时无法读取');
    expect(wrapper.text()).not.toContain('EUR');
    expect(wrapper.find('.latest-grid').exists()).toBe(false);
    expect(mocks.fetch).toHaveBeenNthCalledWith(2, 11, null);
  });

  it('filters by platform, clears the store, and retains platform choices with no data', async () => {
    mocks.fetch
      .mockResolvedValueOnce({ success: true, data: {
        platforms: [{ id: 3, name: 'TikTok', code: 'tiktok' }, { id: 4, name: 'Shopee', code: 'shopee' }],
        stores: managedStores, selected_platform_id: null, selected_store_id: 12, currencies: [],
      } })
      .mockResolvedValueOnce({ success: true, data: {
        platforms: [{ id: 3, name: 'TikTok', code: 'tiktok' }, { id: 4, name: 'Shopee', code: 'shopee' }],
        stores: [], selected_platform_id: 3, selected_store_id: null, currencies: [],
      } });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    expect(wrapper.get('#monthly-sales-store').element.value).toBe('12');
    await wrapper.get('#monthly-sales-platform').setValue('3');
    await flushPromises();
    expect(mocks.fetch.mock.calls).toEqual([[null, null], [null, 3]]);
    expect(wrapper.get('#monthly-sales-platform').element.value).toBe('3');
    expect(wrapper.get('#monthly-sales-platform').text()).toContain('Shopee');
    expect(wrapper.get('#monthly-sales-store').element.value).toBe('');
    expect(wrapper.get('#monthly-sales-store').element.disabled).toBe(true);
  });

  it('shows ad spend as unavailable when either day is missing and handles zero and positive spend', async () => {
    mocks.fetch.mockResolvedValue({ success: true, data: {
      month: '2026-10', through: '2026-10-04', advertising_status: 'available',
      currencies: [{ currency: 'USD', previous: { amount: '1', quantity: 1, ad_spend: '0' }, daily: [
        { date: '2026-10-01', amount: '1', quantity: 1, ad_spend: '0' },
        { date: '2026-10-02', amount: '1', quantity: 1, ad_spend: '2' },
        { date: '2026-10-03', amount: '1', quantity: 1, ad_spend: '0' },
        { date: '2026-10-04', amount: '1', quantity: 1, ad_spend: null },
      ] }],
    } });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    const cards = wrapper.findAll('.day-card');
    expect(cards[0].text()).toContain('持平');
    expect(cards[1].text()).toContain('新增');
    expect(cards[2].text()).toContain('↓100%');
    expect(cards[3].text()).toContain('暂无数据');
    expect(wrapper.get('.advertising-card').text()).toContain('暂无数据');
    expect(wrapper.text()).not.toContain('ad_spend');
  });

  it('shows an explicit no-permission state for advertising spend', async () => {
    mocks.fetch.mockResolvedValue({ success: true, data: {
      month: '2026-10', through: '2026-10-01', advertising_status: 'forbidden',
      currencies: [{ currency: 'USD', previous: { amount: '1', quantity: 1, ad_spend: null }, daily: [] }],
    } });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    expect(wrapper.get('.advertising-card').text()).toContain('无权限');
    expect(wrapper.get('.day-card').text()).toContain('无权限');
  });
  it('disables old stores while switching platforms and ignores an older platform response', async () => {
    const platforms = [{ id: 3, name: 'TikTok' }, { id: 4, name: 'Shopee' }];
    let resolveOld;
    mocks.fetch.mockResolvedValueOnce({ success: true, data: { platforms, stores: managedStores, currencies: [] } })
      .mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ success: true, data: { platforms, stores: [managedStores[1]], selected_platform_id: 4, currencies: [] } });
    const wrapper = mount(MonthlySalesProgress);
    await flushPromises();
    await wrapper.get('#monthly-sales-platform').setValue('3');
    expect(wrapper.get('#monthly-sales-store').element.disabled).toBe(true);
    expect(wrapper.get('#monthly-sales-store').findAll('option')).toHaveLength(1);
    await wrapper.get('#monthly-sales-platform').setValue('4');
    await flushPromises();
    resolveOld({ success: true, data: { platforms, stores: [managedStores[0]], selected_platform_id: 3, currencies: [] } });
    await flushPromises();
    expect(wrapper.get('#monthly-sales-platform').element.value).toBe('4');
    expect(wrapper.get('#monthly-sales-store').findAll('option')[1].element.value).toBe(String(managedStores[1].id));
  });

});
