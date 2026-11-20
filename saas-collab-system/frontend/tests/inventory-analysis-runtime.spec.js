import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { computed } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { normalizeInventoryAnalysisResponse } from '../src/api/uiP6Adapters';

const fetchInventoryAnalysis = vi.hoisted(() => vi.fn());
const inventoryRoute = vi.hoisted(() => ({ query: {} }));
vi.mock('vue-router', async importOriginal => ({ ...await importOriginal(), useRoute: () => inventoryRoute }));
vi.mock('../src/api/analytics', () => ({ fetchInventoryAnalysis }));
import InventoryAnalysis from '../src/views/analytics/InventoryAnalysis.vue';
import Phase3AnalyticsPage from '../src/components/Phase3AnalyticsPage.vue';

const stubs = {
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-button': { template: '<button><slot /></button>' },
  'el-checkbox': { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<label><input type="checkbox" :checked="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.checked); $emit(\'change\', $event.target.checked)" /><slot /></label>' },
  'el-select': { template: '<select><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-date-picker': true, 'el-progress': true, 'el-pagination': true,
  'el-drawer': { props: ['modelValue', 'title'], template: '<aside v-if="modelValue">{{ title }}<slot /></aside>' },
  'el-image': { props: ['src', 'alt'], template: '<img :src="src" :alt="alt">' },
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-table': { props: ['data'], provide() { return { rows: computed(() => this.data) }; }, template: '<div><slot /></div>' },
  'el-table-column': {
    props: ['prop', 'label', 'sortable', 'type'], inject: ['rows'],
    data: () => ({ expanded: null }),
    template: '<section>{{ label }}<template v-for="row in rows"><button v-if="type === &quot;expand&quot;" class="expand" @click="expanded = row.group_key">展开</button><slot v-if="type !== &quot;expand&quot; || expanded === row.group_key" :row="row" /></template></section>'
  },
  'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' },
};

describe('库存分析真实页面', () => {
  beforeEach(() => {
    inventoryRoute.query = {};
    setActivePinia(createPinia());
    fetchInventoryAnalysis.mockReset();
    fetchInventoryAnalysis.mockImplementation(async params => normalizeInventoryAnalysisResponse({ success: true, data: params.group_key ? {
      detail_view: 'sku', count: 25,
      results: [{ id: 1, source_sku: 'FAKE-SKU-001', internal_sku_id: 8, internal_sku: 'NEW-SKU-001',
        legacy_sku_code: 'OLD-SKU-001', warehouse_name: '测试仓', image_url: '/media/sku.jpg' }],
    } : {
      api_status: 'connected', detail_view: 'spu', count: 965, warehouse_options: [{ value: 11, label: '测试仓（THCS）' }],
      quality: { score: 0, total_count: 965, mapped_count: 0, metric_version: 'inventory_snapshot.v1' },
      results: [
        { group_key: 'spu:5', spu_code: 'NEW-SPU-001', legacy_spu_code: 'OLD-SPU-001', product_name: '商品测试', image_url: '/media/spu.jpg',
          on_hand_qty: 12, available_qty: 10, reserved_qty: 2, in_transit_qty: 0 },
        { group_key: 'source:FAKE-SKU-001', unmapped_source: 'FAKE-SKU-001' },
      ],
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

  it('loads ordered SKU details only after expansion and opens the historical drawer', async () => {
    inventoryRoute.query = { include_virtual: 'true' };
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain('NEW-SPU-001');
    expect(wrapper.text()).toContain('OLD-SPU-001');
    expect(wrapper.find('img[alt="NEW-SPU-001"]').attributes('src')).toBe('/media/spu.jpg');
    await wrapper.find('.expand').trigger('click');
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({
      detail_view: 'spu', group_key: 'spu:5', include_virtual: true, page: 1, page_size: 20
    }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(wrapper.text()).toContain('NEW-SKU-001');
    expect(wrapper.text()).toContain('OLD-SKU-001');
    expect(wrapper.find('img[alt="NEW-SKU-001"]').attributes('src')).toBe('/media/sku.jpg');
    const childTable = wrapper.findAllComponents(stubs['el-table'])[1];
    childTable.vm.$emit('sort-change', { prop: 'source_sku', order: 'descending' });
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0].ordering).toBe('-source_sku');
    childTable.vm.$emit('row-click', childTable.props('data')[0]);
    await flushPromises();
    expect(wrapper.find('aside').text()).toContain('库存历史快照');
    expect(wrapper.find('aside').text()).toContain('OLD-SKU-001');
    wrapper.unmount();
  });

  it('exposes alias mode and date controls and gives submitted values priority in the query', async () => {
    inventoryRoute.query = { include_virtual: 'true', sku_mode: 'related', mapping_as_of: '2026-09-19' };
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0].include_virtual).toBe(true);
    expect(wrapper.text()).toContain('同商品新旧编码');
    expect(wrapper.text()).toContain('来源原始编码');
    const page = wrapper.findComponent(Phase3AnalyticsPage);
    await page.props('loader')({ sku_mode: 'source', mapping_as_of: '2026-09-20' });
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ sku_mode: 'source', mapping_as_of: '2026-09-20', include_virtual: true }), undefined);
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
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, risk: 'low' }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    wrapper.unmount();
  });

  it('shows a zero-height bar for zero stock', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    expect(wrapper.findComponent(Phase3AnalyticsPage).vm.barHeight(0)).toBe('0%');
    wrapper.unmount();
  });

  it('toggles virtual products for the whole request and returns to page one', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    const checkbox = wrapper.find('.table-actions input[type="checkbox"]');
    expect(checkbox.element.checked).toBe(false);
    const page = wrapper.findComponent(Phase3AnalyticsPage);
    page.vm.currentPage = 7;
    page.vm.query.risk = 'low';
    await checkbox.setValue(true);
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, risk: 'low', include_virtual: true }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    page.vm.changePage(2);
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0].include_virtual).toBe(true);
    await checkbox.setValue(false);
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, include_virtual: false }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    wrapper.unmount();
  });

  it('sorts remotely from page one, keeps sorting on pagination, and clears on reset', async () => {
    const wrapper = mount(InventoryAnalysis, { global: { stubs } });
    await flushPromises();
    const page = wrapper.findComponent(Phase3AnalyticsPage);
    const columns = wrapper.findAllComponents(stubs['el-table-column']);
    expect(columns.filter(c => c.props('sortable') === 'custom').map(c => c.props('prop')))
      .toEqual(['spu_code', 'legacy_spu_code', 'on_hand_qty', 'available_qty', 'reserved_qty', 'in_transit_qty']);
    page.vm.currentPage = 7;
    page.vm.query.risk = 'low';
    wrapper.findComponent(stubs['el-table']).vm.$emit('sort-change', { prop: 'on_hand_qty', order: 'descending' });
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, risk: 'low', ordering: '-on_hand_qty' }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    page.vm.changePage(2);
    await flushPromises();
    expect(fetchInventoryAnalysis).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, ordering: '-on_hand_qty' }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    page.vm.changeSort({ prop: 'on_hand_qty', order: 'ascending' });
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0].ordering).toBe('on_hand_qty');
    page.vm.changeSort({ prop: 'on_hand_qty', order: null });
    await flushPromises();
    expect(fetchInventoryAnalysis.mock.lastCall[0]).not.toHaveProperty('ordering');
    page.vm.changeSort({ prop: 'spu_code', order: 'ascending' });
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
