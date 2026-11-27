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
  'el-dropdown': true, 'el-icon': true, 'el-alert': true, 'el-empty': true,
};
describe('inventory more analysis navigation', () => {
  beforeEach(() => { mocks.sales = true; mocks.fetch.mockReset().mockResolvedValue({ success: true, data: { warehouses: [] } }); });
  it('keeps authorized operations available and hides the retired more-analysis entry', async () => {
    const wrapper = mount(InventoryWorkbench, { global: { stubs } }); await flushPromises();
    expect(wrapper.get('[data-testid="decisions"]').text()).toBe('operations');
    expect(wrapper.text()).not.toContain('更多分析');
    expect(mocks.fetch).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('opens warehouse details directly, including when switching from the workbench', async () => {
    const wrapper = mount(InventoryWorkbench, { global: { stubs } });
    await wrapper.setProps({ warehouseDetails: true });
    await flushPromises();
    expect(wrapper.get('h1').text()).toBe('仓库库存明细');
    expect(wrapper.find('[data-testid="decisions"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('更多分析');
    expect(mocks.fetch).toHaveBeenCalledOnce();
    await wrapper.setProps({ warehouseDetails: false });
    expect(wrapper.get('[data-testid="decisions"]').text()).toBe('operations');
    wrapper.unmount();
  });
  it('loads summary first, drills into a category, and resets to summary', async () => {
    mocks.fetch.mockResolvedValue({ success: true, data: { warehouses: [{ warehouse_id: 1, warehouse_name: 'Test' }], sales_category_counts: { sales_no_stock: 8, sales_unknown: 0 } } });
    const wrapper = mount(InventoryWorkbench, { props: { warehouseDetails: true }, global: { stubs } });
    await flushPromises();
    expect(mocks.fetch.mock.lastCall[0]).toMatchObject({ sales_report: true, summary_only: true });
    expect(wrapper.find('.focus-table').exists()).toBe(false);
    const category = wrapper.findAll('.workbench-metric').find(button => button.text().includes('无库存有销售'));
    expect(category.text()).toContain('8');
    const unavailable = wrapper.findAll('.workbench-metric').find(button => button.text().includes('有库存无销售'));
    expect(unavailable.get('strong').text()).toBe('—');
    const zero = wrapper.findAll('.workbench-metric').find(button => button.text().includes('销量待核查'));
    expect(zero.get('strong').text()).toBe('0');
    await category.trigger('click');
    await flushPromises();
    expect(mocks.fetch.mock.lastCall[0]).toMatchObject({ summary_only: false, risk: 'sales_no_stock' });
    expect(wrapper.find('.focus-table').exists()).toBe(true);
    await wrapper.findAll('button').find(button => button.text() === '重置筛选').trigger('click');
    await flushPromises();
    expect(mocks.fetch.mock.lastCall[0]).toMatchObject({ summary_only: true });
    expect(wrapper.find('.focus-table').exists()).toBe(false);
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
