import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchSalesPage: vi.fn() }));
vi.mock('../src/api/salesManagement', () => api);
import SalesOverviewSkus from '../src/views/sales-management/SalesOverviewSkus.vue';
const render = () => mount(SalesOverviewSkus, { props: { filters: { platform: 'shopee', currency: 'PHP', date_from: '2026-09-01', date_to: '2026-09-10' } }, global: { stubs: {
  'el-input': true, 'el-button': { template: '<button><slot /></button>' },
  'el-table': true, 'el-table-column': true, 'el-pagination': true,
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' }
}, directives: { loading: () => {} } } });
beforeEach(() => { api.fetchSalesPage.mockReset(); api.fetchSalesPage.mockResolvedValue({ success: true, data: { results: [{ seller_sku: 'TEST-SKU' }], count: 41 } }); });
describe('总览 SKU 明细', () => {
  it('passes the applied parent filters to the existing paginated endpoint', async () => {
    const wrapper = render(); await flushPromises();
    expect(api.fetchSalesPage).toHaveBeenCalledWith('skus', { platform: 'shopee', currency: 'PHP', date_from: '2026-09-01', date_to: '2026-09-10', page: 1, page_size: 20 });
    wrapper.vm.page = 2; await wrapper.vm.load();
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith('skus', expect.objectContaining({ page: 2 }));
    wrapper.vm.draft = ' TEST '; wrapper.vm.search(); await flushPromises();
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith('skus', expect.objectContaining({ page: 1, sku: 'TEST' }));
    wrapper.unmount();
  });
  it('resets pagination on new filters and clears stale rows when the request fails', async () => {
    const wrapper = render(); await flushPromises(); wrapper.vm.page = 3;
    api.fetchSalesPage.mockResolvedValueOnce({ success: false, message: '读取失败' });
    await wrapper.setProps({ filters: { platform: 'tiktok' } }); await flushPromises();
    expect(wrapper.vm.page).toBe(1); expect(wrapper.vm.rows).toEqual([]); expect(wrapper.vm.total).toBe(0);
    expect(wrapper.text()).toContain('读取失败'); wrapper.unmount();
  });
  it('ignores stale responses and offers real field visibility controls', async () => {
    let finish;
    api.fetchSalesPage.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = render();
    await wrapper.setProps({ filters: { currency: 'THB' } }); await flushPromises();
    finish({ success: true, data: { results: [{ seller_sku: 'OLD' }], count: 1 } }); await flushPromises();
    expect(wrapper.vm.total).toBe(41);
    const count = wrapper.vm.shownColumns.length;
    await wrapper.find('.column-options input').setValue(false);
    expect(wrapper.vm.shownColumns.length).toBe(count - 1); wrapper.unmount();
  });
});
