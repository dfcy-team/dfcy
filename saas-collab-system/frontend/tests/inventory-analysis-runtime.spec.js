import { mount, flushPromises } from '@vue/test-utils';
import { computed } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { normalizeInventoryAnalysisResponse } from '../src/api/uiP6Adapters';

const fetchInventoryAnalysis = vi.hoisted(() => vi.fn());
vi.mock('../src/api/analytics', () => ({ fetchInventoryAnalysis }));
import InventoryAnalysis from '../src/views/analytics/InventoryAnalysis.vue';
import Phase3AnalyticsPage from '../src/components/Phase3AnalyticsPage.vue';

const stubs = {
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-button': { template: '<button><slot /></button>' },
  'el-select': { template: '<select><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-date-picker': true, 'el-progress': true, 'el-pagination': true,
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-table': { props: ['data'], provide() { return { rows: computed(() => this.data) }; }, template: '<div><slot /></div>' },
  'el-table-column': { props: ['label', 'sortable'], inject: ['rows'], template: '<section>{{ label }}<slot v-for="row in rows" :row="row" /></section>' },
  'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' },
};

describe('库存分析真实页面', () => {
  beforeEach(() => {
    fetchInventoryAnalysis.mockReset();
    fetchInventoryAnalysis.mockResolvedValue(normalizeInventoryAnalysisResponse({ success: true, data: {
      api_status: 'connected', count: 965, warehouse_options: [{ value: 11, label: '测试仓（THCS）' }],
      quality: { score: 0, total_count: 965, mapped_count: 0, metric_version: 'inventory_snapshot.v1' },
      results: [{ source_sku: 'FAKE-SKU-001', warehouse_code: 'THCS', warehouse_name: '测试仓', on_hand_qty: 12, available_qty: 10, reserved_qty: 2, in_transit_qty: 0, risk_label: '正常' }],
      trend: [{ date: '2026-09-11', total: 12 }],
    } }));
  });

  it('renders warehouse facts and explains unmapped SKU and single-day history', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('SKU 映射率');
    expect(wrapper.text()).not.toContain('数据可信度');
    expect(wrapper.text()).toContain('FAKE-SKU-001');
    expect(wrapper.text()).toContain('未关联');
    expect(wrapper.text()).toContain('仅有 1 天');
    expect(wrapper.text()).not.toContain('演示');
    expect(wrapper.findAll('option').map(option => option.text())).toContain('测试仓（THCS）');
    wrapper.unmount();
  });

  it('returns to page one when applying a changed risk filter', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    const page = wrapper.findComponent(Phase3AnalyticsPage);
    page.vm.currentPage = 7;
    page.vm.query.risk = 'low';
    await wrapper.find('form').trigger('submit');
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, risk: 'low' }));
    wrapper.unmount();
  });

  it('shows a zero-height bar for zero stock', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    expect(wrapper.findComponent(Phase3AnalyticsPage).vm.barHeight(0)).toBe('0%');
    wrapper.unmount();
  });

  it('sorts remotely from page one, keeps sorting on pagination, and clears on reset', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    const page = wrapper.findComponent(Phase3AnalyticsPage);
    expect(wrapper.findAllComponents(stubs['el-table-column']).every(c => c.props('sortable') === 'custom')).toBe(true);
    page.vm.currentPage = 7;
    page.vm.query.risk = 'low';
    wrapper.findComponent(stubs['el-table']).vm.$emit('sort-change', { prop: 'on_hand_qty', order: 'descending' });
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, risk: 'low', ordering: '-on_hand_qty' }));
    page.vm.changePage(2);
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, ordering: '-on_hand_qty' }));
    page.vm.changeSort({ prop: 'on_hand_qty', order: 'ascending' });
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0].ordering).toBe('on_hand_qty');
    page.vm.changeSort({ prop: 'on_hand_qty', order: null });
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0]).not.toHaveProperty('ordering');
    page.vm.changeSort({ prop: 'source_sku', order: 'ascending' });
    await flushPromises();
    page.vm.resetFilters();
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0]).not.toHaveProperty('ordering');
    expect(fetchInventoryAnalysis.mock.lastCall[0].page).toBe(1);
    wrapper.unmount();
  });

  it('ignores stale responses when quickly switching sort direction', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    let resolveOld;
    fetchInventoryAnalysis.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const page = wrapper.findComponent(Phase3AnalyticsPage);
    page.vm.changeSort({ prop: 'on_hand_qty', order: 'ascending' });
    page.vm.changeSort({ prop: 'on_hand_qty', order: 'descending' });
    await flushPromises();
    resolveOld({ success: true, data: { results: [{ source_sku: 'STALE' }], count: 1 } });
    await flushPromises();
    expect(wrapper.text()).not.toContain('STALE');
    expect(wrapper.text()).toContain('FAKE-SKU-001');
    wrapper.unmount();
  });
});
