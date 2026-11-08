import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ sales: true, fetch: vi.fn() }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: {}, authorizationStale: false, hasPermission: code => code === 'sales_management.skus.view' ? mocks.sales : false }) }));
vi.mock('../src/api/analytics', () => ({ fetchInventoryWorkbench: mocks.fetch }));
vi.mock('../src/router/menu', () => ({ canAccessPath: () => false }));
import InventoryWorkbench from '../src/views/inventory/InventoryWorkbench.vue';
const stubs = {
  CountryInventoryDecisions: { props: { mode: { default: 'summary' } }, template: '<p data-testid="decisions">{{ mode }}</p>' },
  BusinessDashboardLink: true, InventoryPeriodComparison: true,
  'el-button': { emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
  'el-dropdown': { emits: ['command'], template: '<div><slot/><button @click="$emit(\'command\', \'summary\')">选择旧汇总</button><button @click="$emit(\'command\', \'snapshot\')">选择原始快照</button></div>' },
  'el-icon': true, 'el-alert': true, 'el-empty': true,
};
describe('inventory more analysis navigation', () => {
  beforeEach(() => { mocks.sales = true; mocks.fetch.mockReset().mockResolvedValue({ success: true, data: { warehouses: [] } }); });
  it('opens legacy views and returns to operations without changing routes', async () => {
    const wrapper = mount(InventoryWorkbench, { global: { stubs } }); await flushPromises();
    expect(wrapper.get('[data-testid="decisions"]').text()).toBe('operations');
    expect(mocks.fetch).not.toHaveBeenCalled();
    await wrapper.findAll('button').find(b => b.text() === '选择旧汇总').trigger('click');
    expect(wrapper.get('[data-testid="decisions"]').text()).toBe('summary');
    await wrapper.findAll('button').find(b => b.text() === '选择原始快照').trigger('click'); await flushPromises();
    expect(mocks.fetch).toHaveBeenCalledOnce();
    await wrapper.findAll('button').find(b => b.text() === '库存经营').trigger('click');
    expect(wrapper.get('[data-testid="decisions"]').text()).toBe('operations');
    wrapper.unmount();
  });
  it('keeps inventory-only users on authorized stock snapshots', async () => {
    mocks.sales = false;
    const wrapper = mount(InventoryWorkbench, { global: { stubs } }); await flushPromises();
    expect(wrapper.find('[data-testid="decisions"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('库存经营');
    expect(mocks.fetch).toHaveBeenCalledOnce();
    wrapper.unmount();
  });
});
