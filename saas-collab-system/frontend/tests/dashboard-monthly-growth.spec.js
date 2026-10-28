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
    expect(wrapper.text()).toContain('本月可见范围内暂无销售订单');
    expect(mocks.fetch).toHaveBeenCalledWith(null);
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
    expect(mocks.fetch.mock.calls.map(([id]) => id)).toEqual([null, 11, 12]);
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
    expect(mocks.fetch).toHaveBeenNthCalledWith(2, 11);
  });
});
