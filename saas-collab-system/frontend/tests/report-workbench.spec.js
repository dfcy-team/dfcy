import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

const api = vi.hoisted(() => ({ fetchReportDatasets: vi.fn(), queryReport: vi.fn(), saveReportView: vi.fn(), createReportExport: vi.fn() }));
const auth = vi.hoisted(() => ({ currentUser: { permissions: ['reports.view', 'reports.export', 'sales_management.export'] }, hasPermission(code) { return this.currentUser?.is_superuser || this.currentUser?.permissions?.includes(code); } }));
const nav = vi.hoisted(() => ({ route: { query: {} }, push: vi.fn() }));
vi.mock('../src/api/reporting', () => api);
vi.mock('../src/api/reportExports', () => ({ createReportExport: api.createReportExport }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('../src/router/menu', () => ({ canAccessPath: () => true }));
vi.mock('vue-router', () => ({ useRoute: () => nav.route, useRouter: () => ({ push: nav.push }) }));

import ReportWorkbench from '../src/views/reports/ReportWorkbench.vue';

const dataset = { id: 'sales', name: '销售报表', module: '销售', path: '/sales/orders', filters: ['date_from', 'date_to', 'store_id', 'platform'], dimensions: [{ key: 'store_id', label: '店铺' }, { key: 'platform', label: '平台' }, { key: 'date', label: '日期' }], metrics: [{ key: 'revenue', label: '销售额', kind: 'money' }], defaults: { dimensions: ['store_id'], metrics: ['revenue'] } };
const result = (config, rows = []) => ({ success: true, data: { config: structuredClone(config), rows, columns: [{ key: 'store_id', label: '店铺' }, { key: 'revenue', label: '销售额' }], count: rows.length, metric_version: 'v1', cache_seconds: 60, refreshed_at: '', note: '' } });
const stubs = {
  'el-button': { props: ['disabled'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-select': { template: '<select><slot /></select>' }, 'el-option': { template: '<option><slot /></option>' },
  'el-form': { template: '<form @submit.prevent="$emit(\'submit\')"><slot /></form>' }, 'el-form-item': { template: '<label><slot /></label>' },
  'el-tag': true, 'el-alert': { props: ['title'], template: '<div>{{title}}</div>' }, 'el-empty': true, 'el-checkbox': true,
  'el-dialog': { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
  'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)" />' },
  'el-table': { props: ['data'], template: '<div><slot v-for="row in data" :row="row" /></div>' },
  'el-table-column': { template: '<div><slot v-for="row in $parent.$props.data || []" :row="row" /></div>' },
  'el-date-picker': true
};
const mountPage = props => mount(ReportWorkbench, { props, global: { stubs } });

describe('ReportWorkbench', () => {
  it('retains the last successful scope on timeout but clears it on authorization rejection', async () => {
    const wrapper = mountPage(); await flushPromises();
    const prior = JSON.parse(JSON.stringify(wrapper.vm.result));
    api.queryReport.mockResolvedValueOnce({ success: false, http_status: 504, message: '读取超时' });
    await wrapper.vm.run();
    expect(wrapper.vm.result).toEqual(prior);
    expect(wrapper.text()).toContain('保留上次成功结果');
    expect(wrapper.findAll('button').find(b => b.text().includes('导出已查询结果')).element.disabled).toBe(true);
    wrapper.vm.drill({ store_id: 1 }); expect(nav.push).not.toHaveBeenCalled();
    api.queryReport.mockResolvedValueOnce({ success: false, http_status: 403, message: '请求错误' });
    await wrapper.vm.run(); expect(wrapper.vm.result).toBeNull();
    wrapper.unmount();
  });
  it('updates an owned saved configuration with its expected version', async () => {
    const wrapper = mountPage({ savedView: { id: 4, name: '当前报表', is_owner: true, is_shared: false, version: 3 } }); await flushPromises();
    api.saveReportView.mockResolvedValueOnce({ success: true, data: { version: 4 } });
    await wrapper.findAll('button').find(b => b.text() === '更新当前视图版本').trigger('click'); await flushPromises();
    expect(api.saveReportView).toHaveBeenCalledWith(expect.objectContaining({ expected_version: 3, name: '当前报表' }), 4);
    wrapper.unmount();
  });
  beforeEach(() => {
    vi.clearAllMocks(); nav.route.query = {};
    auth.currentUser = { permissions: ['reports.view', 'reports.export', 'sales_management.export'] };
    api.fetchReportDatasets.mockResolvedValue({ success: true, data: { datasets: [dataset] } });
    api.queryReport.mockImplementation(config => Promise.resolve(result(config)));
    api.saveReportView.mockResolvedValue({ success: true });
    api.createReportExport.mockResolvedValue({ success: true, data: { status: 'queued' } });
  });

  it('restores and saves the selected chart metric with a saved view', async () => {
    const saved = { dataset: 'sales', dimensions: ['store_id'], metrics: ['revenue'], filters: {}, chart: 'bar', chart_metric: 'revenue', pivot: '', ordering: '' };
    const wrapper = mountPage({ viewConfig: saved }); await flushPromises();
    expect(wrapper.vm.config.chart_metric).toBe('revenue');
    const saveButton = wrapper.findAll('button').find(button => button.text() === '保存视图');
    expect(saveButton).toBeTruthy();
    await saveButton.trigger('click');
    await flushPromises();
    await wrapper.find('[data-testid="report-view-name"]').setValue('常用分析');
    await wrapper.findAll('button').at(-1).trigger('click'); await flushPromises();
    expect(api.saveReportView).toHaveBeenCalledWith(expect.objectContaining({ config: expect.objectContaining({ chart_metric: 'revenue' }) }));
  });

  it('blocks export and drill after filters change until the query is reapplied', async () => {
    auth.currentUser = { is_superuser: true };
    const wrapper = mountPage(); await flushPromises();
    wrapper.vm.config.filters.store_id = 'store-b'; await flushPromises();
    const exportButton = wrapper.findAll('button').find(button => button.text().includes('导出已查询结果'));
    expect(exportButton.element.disabled).toBe(true);
    wrapper.vm.drill({ store_id: 'store-a' });
    expect(nav.push).not.toHaveBeenCalled();
    await wrapper.vm.run();
    expect(wrapper.findAll('button').find(button => button.text().includes('导出已查询结果')).element.disabled).toBe(false);
  });

  it('keeps the selected group, filters, and date in the source drill route', async () => {
    const wrapper = mountPage(); await flushPromises();
    wrapper.vm.config.filters = { date_from: '2026-01-01', date_to: '2026-01-31', store_id: 'filter-store', platform: 'web' };
    await wrapper.vm.run();
    wrapper.vm.drill({ store_id: 'group-store', platform: 'app', date: '2026-01-17' });
    expect(nav.push).toHaveBeenCalledWith({ path: '/sales/orders', query: expect.objectContaining({ store_id: 'group-store', platform: 'app', date_from: '2026-01-17', date_to: '2026-01-17' }) });
  });

  it('preserves plural store and platform route filters', async () => {
    nav.route.query = { store_ids: ['s1', 's2'], platforms: ['web', 'app'] };
    const wrapper = mountPage(); await flushPromises();
    expect(api.queryReport).toHaveBeenLastCalledWith(expect.objectContaining({ filters: expect.objectContaining({ store_ids: 's1,s2', platforms: 'web,app' }) }), expect.anything());
    wrapper.unmount();
  });

  it('keeps missing monetary chart values empty instead of drawing a zero mark', async () => {
    api.queryReport.mockImplementationOnce(config => Promise.resolve(result(config, [{ store_id: 's1', revenue: null }])));
    const wrapper = mountPage({ viewConfig: { dataset: 'sales', dimensions: ['store_id'], metrics: ['revenue'], filters: {}, chart: 'bar', chart_metric: 'revenue', pivot: '', ordering: '' } });
    await flushPromises();
    expect(wrapper.findAll('rect').length).toBe(0);
    expect(wrapper.text()).toContain('—');
  });
  it('submits alias matching mode and its historical effective date as report filters', async () => {
    const wrapper = mountPage(); await flushPromises();
    wrapper.vm.config.filters.sku_mode = 'source';
    wrapper.vm.config.filters.mapping_as_of = '2026-09-20';
    await wrapper.vm.run();
    expect(api.queryReport).toHaveBeenLastCalledWith(expect.objectContaining({ filters: expect.objectContaining({ sku_mode: 'source', mapping_as_of: '2026-09-20' }) }), expect.anything());
  });
  it('does not restore an old dataset after switching while its request is pending', async () => {
    let complete;
    api.fetchReportDatasets.mockResolvedValue({ success: true, data: { datasets: [dataset, { ...dataset, id: 'refunds' }] } });
    api.queryReport.mockImplementationOnce(config => new Promise(resolve => { complete = () => resolve(result(config)); }));
    const wrapper = mountPage(); await flushPromises();
    wrapper.vm.config.dataset = 'refunds'; wrapper.vm.chooseDataset();
    complete(); await flushPromises();
    expect(wrapper.vm.config.dataset).toBe('refunds');
    expect(wrapper.vm.result).toBeNull();
    wrapper.unmount();
  });
});
