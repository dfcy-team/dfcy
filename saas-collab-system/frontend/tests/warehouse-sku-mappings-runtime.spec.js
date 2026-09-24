import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchWarehouseSkus: vi.fn(), fetchWarehouseSkuMapping: vi.fn(), confirmWarehouseSkuMapping: vi.fn(), downloadWarehouseSkus: vi.fn() }));
const hasPermission = vi.hoisted(() => vi.fn(() => true));
vi.mock('../src/api/platformProductDetails', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission }) }));
import WarehouseSkuMappings from '../src/components/WarehouseSkuMappings.vue';
const row = { id: 5, warehouse_name: '测试仓库', source_sku: 'ALIAS' };
const stubs = {
  'el-form': { template: '<form><slot /></form>' }, 'el-form-item': { template: '<div><slot /></div>' },
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-button': { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' },
  'el-select': { template: '<div><slot /></div>' }, 'el-option': true, 'el-input': true,
  'el-checkbox': true, 'el-tag': true, 'el-table': true, 'el-table-column': true, 'el-pagination': true,
  'el-drawer': { template: '<div><slot /><slot name="footer" /></div>' },
};
describe('warehouse SKU mapping', () => {
  beforeEach(() => {
    vi.clearAllMocks(); hasPermission.mockReturnValue(true);
    api.fetchWarehouseSkus.mockResolvedValue({ success: true, data: { count: 1, results: [row], warehouse_options: [] } });
    api.fetchWarehouseSkuMapping.mockResolvedValue({ success: true, data: { current_sku_ids: [], suggested_sku_id: 8, rule: 'exact_catalogue_code', candidates: [{ id: 8, sku_code: 'NEW' }] } });
    api.confirmWarehouseSkuMapping.mockResolvedValue({ success: true, data: { updated_count: 1 } });
    api.downloadWarehouseSkus.mockResolvedValue({ success: true });
  });
  it('loads without writing, confirms explicitly, then reloads from page one', async () => {
    const wrapper = mount(WarehouseSkuMappings, { global: { stubs } });
    await flushPromises();
    expect(api.confirmWarehouseSkuMapping).not.toHaveBeenCalled();
    await wrapper.vm.openMapping(row);
    await wrapper.vm.save();
    expect(api.confirmWarehouseSkuMapping).not.toHaveBeenCalled();
    wrapper.vm.confirmed = true;
    await wrapper.vm.save(); await flushPromises();
    expect(api.confirmWarehouseSkuMapping).toHaveBeenCalledWith(5, { sku_id: 8, expected_sku_ids: [], confirmed: true });
    expect(api.fetchWarehouseSkus.mock.lastCall[0].page).toBe(1);
    wrapper.unmount();
  });
  it('view-only users cannot save a mapping', async () => {
    hasPermission.mockReturnValue(false);
    const wrapper = mount(WarehouseSkuMappings, { global: { stubs } });
    await flushPromises(); await wrapper.vm.openMapping(row);
    wrapper.vm.confirmed = true;
    await wrapper.vm.save();
    expect(api.confirmWarehouseSkuMapping).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('没有 SKU 映射确认权限');
    wrapper.unmount();
  });
  it('keeps filters when changing pages and shows failed confirmation', async () => {
    const wrapper = mount(WarehouseSkuMappings, { global: { stubs } });
    await flushPromises();
    wrapper.vm.query.warehouse_id = 11; wrapper.vm.query.status = 'unmapped';
    wrapper.vm.changePage(2); await flushPromises();
    expect(api.fetchWarehouseSkus.mock.lastCall[0]).toMatchObject({ warehouse_id: 11, status: 'unmapped', page: 2 });
    await wrapper.vm.openMapping(row); wrapper.vm.confirmed = true;
    api.confirmWarehouseSkuMapping.mockResolvedValueOnce({ success: false, message: '映射已变化，请刷新' });
    await wrapper.vm.save();
    expect(wrapper.vm.mappingVisible).toBe(true);
    expect(wrapper.text()).toContain('映射已变化');
    wrapper.unmount();
  });
  it('exports all rows under the current filters instead of only the current page', async () => {
    const wrapper = mount(WarehouseSkuMappings, { global: { stubs } });
    await flushPromises();
    wrapper.vm.query.warehouse_id = 11; wrapper.vm.query.search = 'ALIAS'; wrapper.vm.query.status = 'unmapped'; wrapper.vm.query.page = 3;
    await wrapper.vm.exportRows();
    expect(api.downloadWarehouseSkus).toHaveBeenCalledWith({ warehouse_id: 11, search: 'ALIAS', status: 'unmapped' });
    expect(wrapper.text()).toContain('导出');
    wrapper.unmount();
  });
});
