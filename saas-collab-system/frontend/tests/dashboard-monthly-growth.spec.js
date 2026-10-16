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
});
