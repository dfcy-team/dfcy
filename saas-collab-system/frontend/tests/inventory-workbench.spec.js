import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchInventoryWorkbench = vi.hoisted(() => vi.fn());
vi.mock('../src/api/analytics', () => ({ fetchInventoryWorkbench }));
import InventoryWorkbench from '../src/views/inventory/InventoryWorkbench.vue';

const stubs = {
  'router-link': { props: ['to'], template: '<a><slot /></a>' },
  'el-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  'el-checkbox': { props: ['modelValue'], emits: ['update:modelValue', 'change'], template: '<label><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked); $emit(\'change\')" /><slot /></label>' },
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' },
  'el-tabs': { template: '<div><slot /></div>' },
  'el-tab-pane': { props: ['label'], template: '<div>{{ label }}</div>' },
  'el-select': { template: '<select><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-input': { template: '<input />' },
  'el-table': { props: ['data'], template: '<div><slot /></div>' },
  'el-table-column': { template: '<div><slot :row="{}" /></div>' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-drawer': { props: ['modelValue'], template: '<aside v-if="modelValue"><slot /></aside>' },
};

const stock = {
  refreshed_at: '2026-09-23T00:00:00Z', freshness: { status: 'fresh' },
  totals: { on_hand: 100, available: 72, reserved: 28 },
  risk_counts: { out: 2, low: 3, locked: 1, healthy: 4 },
  mapping_counts: { mapped: 8, unmapped: 2 }, focus_limit: 50,
  warehouses: [{ warehouse_id: 1, warehouse_name: '测试仓', warehouse_code: 'T1', at_risk: 6, unmapped: 2 }],
  trend: [{ date: '2026-09-22', total: 90, available: 60 }, { date: '2026-09-23', total: 100, available: 72 }],
  focus: [{ warehouse_id: 1, warehouse_name: '测试仓', source_sku: 'SOURCE-1', internal_sku: null, available_qty: 0, reserved_qty: 0, risk: 'out', mapping_status: 'unmapped', snapshot_at_utc: '2026-09-23T00:00:00Z' }],
};

describe('库存工作台', () => {
  beforeEach(() => { fetchInventoryWorkbench.mockReset(); fetchInventoryWorkbench.mockResolvedValue({ success: true, data: stock }); });

  it('loads real scoped stock without virtual products and switches business perspective', async () => {
    const wrapper = mount(InventoryWorkbench, { global: { stubs } });
    await flushPromises();
    expect(fetchInventoryWorkbench).toHaveBeenCalledWith({ include_virtual: false, perspective: 'operations' }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(wrapper.text()).toContain('缺货 SKU');
    expect(wrapper.text()).toContain('风险最多的前 8 仓');
    wrapper.vm.perspective = 'product';
    await wrapper.vm.$nextTick();
    wrapper.vm.changePerspective();
    await flushPromises();
    expect(fetchInventoryWorkbench).toHaveBeenLastCalledWith({ include_virtual: false, perspective: 'product' }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(wrapper.text()).toContain('未关联最多的前 8 仓');
    expect(wrapper.text()).toContain('商品运营待核查清单');
    wrapper.unmount();
  });

  it('shows API errors and does not present an empty stock state as success', async () => {
    fetchInventoryWorkbench.mockResolvedValue({ success: false, code: 'VALIDATION_ERROR', message: '请求错误', http_status: 400, data: { perspective: ['请选择业务视角。'] } });
    const wrapper = mount(InventoryWorkbench, { global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('VALIDATION_ERROR');
    expect(wrapper.text()).toContain('perspective：请选择业务视角。');
    expect(wrapper.text()).not.toContain('暂无极风 WMS 库存快照');
    wrapper.unmount();
  });

  it('includes virtual products only after an explicit checkbox choice', async () => {
    const wrapper = mount(InventoryWorkbench, { global: { stubs } });
    await flushPromises();
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await flushPromises();
    expect(fetchInventoryWorkbench).toHaveBeenLastCalledWith(
      { include_virtual: true, perspective: 'operations' },
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    wrapper.unmount();
  });

  it('queries the server for warehouse and SKU instead of filtering only the first 50 rows', async () => {
    const wrapper = mount(InventoryWorkbench, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selectWarehouse(1);
    await flushPromises();
    expect(fetchInventoryWorkbench).toHaveBeenLastCalledWith(
      { include_virtual: false, perspective: 'operations', warehouse_id: 1 },
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    wrapper.vm.skuSearch = 'SOURCE-99';
    wrapper.vm.load();
    await flushPromises();
    expect(fetchInventoryWorkbench).toHaveBeenLastCalledWith(
      { include_virtual: false, perspective: 'operations', warehouse_id: 1, sku: 'SOURCE-99' },
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    wrapper.vm.clearFocusFilters();
    await flushPromises();
    expect(fetchInventoryWorkbench).toHaveBeenLastCalledWith(
      { include_virtual: false, perspective: 'operations' },
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    wrapper.unmount();
  });

  it('opens stock details in place without requiring analytics permission', async () => {
    const wrapper = mount(InventoryWorkbench, { global: { stubs } });
    await flushPromises();
    wrapper.vm.openDetail(stock.focus[0]);
    await wrapper.vm.$nextTick();
    expect(wrapper.find('aside').text()).toContain('SOURCE-1');
    expect(wrapper.find('aside').text()).toContain('可用库存');
    wrapper.unmount();
  });
});
