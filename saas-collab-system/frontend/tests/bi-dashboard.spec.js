import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const api = vi.hoisted(() => ({ fetchReportDatasets: vi.fn(), queryReport: vi.fn(), createReportExport: vi.fn() }));
const auth = vi.hoisted(() => ({ currentUser: { permissions: ['reports.view'] }, hasPermission: () => true }));
const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('../src/api/reporting', () => ({ ...api, saveReportView: vi.fn() }));
vi.mock('../src/api/reportExports', () => ({ createReportExport: api.createReportExport }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('../src/router/menu', () => ({ canAccessPath: () => true }));
vi.mock('vue-router', () => ({ useRouter: () => nav }));

import ReportDashboard from '../src/views/reports/ReportDashboard.vue';

const sales = { id: 'sales', name: '销售', module: '销售管理', path: '/orders', filters: ['date_from', 'date_to', 'store_id', 'platform'], dimensions: [{ key: 'store_id', label: '店铺' }, { key: 'platform', label: '平台' }, { key: 'currency', label: '币种' }], metrics: [{ key: 'gross_sales', label: '销售额', kind: 'money' }], defaults: { dimensions: ['store_id', 'currency'], metrics: ['gross_sales'] } };
const inventory = { id: 'inventory', name: '库存', module: '库存管理', path: '/inventory', filters: ['warehouse_id', 'site_code'], dimensions: [{ key: 'warehouse_id', label: '仓库' }, { key: 'sku', label: 'SKU' }], metrics: [{ key: 'on_hand', label: '库存' }], defaults: { dimensions: ['warehouse_id'], metrics: ['on_hand'] } };
const config = (dataset = 'sales') => ({ kind: 'dashboard', version: 1, module: '经营分析', filters: {}, widgets: [{ id: 'a', type: 'bar', title: 'A', width: 6, height: 360, config: { dataset, dimensions: dataset === 'sales' ? ['store_id', 'currency'] : ['warehouse_id'], metrics: [dataset === 'sales' ? 'gross_sales' : 'on_hand'], filters: {}, chart: 'bar', chart_metric: dataset === 'sales' ? 'gross_sales' : 'on_hand', pivot: '', ordering: '' } }] });
const response = cfg => ({ success: true, data: { config: cfg, rows: [], columns: [], count: 0 } });
const stubs = { 'el-button': { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' }, 'el-select': { template: '<select><slot /></select>' }, 'el-option': true, 'el-alert': { props: ['title'], template: '<p>{{title}}</p>' }, 'el-empty': true, 'el-input': true, 'el-date-picker': true, 'el-dialog': true, 'el-drawer': { template: '<div><slot /></div>' }, 'el-input-number': true, 'el-checkbox': true };
const mountDashboard = viewConfig => mount(ReportDashboard, { props: { viewConfig }, global: { stubs } });

describe('ReportDashboard interactions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchReportDatasets.mockResolvedValue({ success: true, data: { datasets: [sales, inventory] } });
    api.queryReport.mockImplementation(async cfg => response(cfg));
    api.createReportExport.mockResolvedValue({ success: true, data: { status: 'ready' } });
  });

  it('adds authorized components and reorders them', async () => {
    const wrapper = mountDashboard(config()); await flushPromises();
    wrapper.vm.addWidget('line');
    wrapper.vm.addWidget('card');
    const ids = wrapper.vm.board.widgets.map(w => w.id);
    wrapper.vm.moveWidget(ids[2], 0);
    expect(wrapper.vm.board.widgets.map(w => w.id)).toEqual([ids[2], ids[0], ids[1]]);
    expect(wrapper.vm.board.widgets[0].config.dataset).toBe('sales');
  });

  it('sends only supported global filters to a dataset query', async () => {
    const wrapper = mountDashboard(config()); await flushPromises();
    wrapper.vm.board.filters = { store_id: 'store-1', platform: 'web', warehouse_id: 'wh-9' };
    await wrapper.vm.run();
    expect(api.queryReport).toHaveBeenLastCalledWith(expect.objectContaining({ filters: expect.objectContaining({ store_id: 'store-1', platform: 'web' }) }), expect.any(AbortSignal));
    expect(api.queryReport.mock.calls.at(-1)[0].filters).not.toHaveProperty('warehouse_id');
    wrapper.unmount();
  });

  it('selects a result row, links peers, and clears the link by requerying', async () => {
    const board = config(); board.widgets[0].config.dimensions.push('platform'); board.widgets.push({ ...structuredClone(board.widgets[0]), id: 'b', config: { ...structuredClone(board.widgets[0].config), dataset: 'sales' } });
    const wrapper = mountDashboard(board); await flushPromises();
    const row = { store_id: 'store-2', platform: 'app', currency: 'USD' };
    wrapper.vm.selectRow(wrapper.vm.board.widgets[0], row); await flushPromises();
    expect(wrapper.vm.link.filters).toEqual({ store_id: 'store-2', platform: 'app', currency: 'USD' });
    expect(api.queryReport.mock.calls.at(-1)[0].filters).toMatchObject({ store_id: 'store-2', platform: 'app' });
    wrapper.find('.link-banner button').trigger('click'); await flushPromises();
    expect(wrapper.vm.link).toBeNull();
    expect(api.queryReport.mock.calls.at(-1)[0].filters).not.toHaveProperty('store_id');
    wrapper.unmount();
  });

  it('ignores stale query results when an older promise resolves last', async () => {
    let resolveOld;
    api.queryReport.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const wrapper = mountDashboard(config()); await flushPromises();
    const oldCall = wrapper.vm.run();
    const newCall = wrapper.vm.run(); await flushPromises();
    resolveOld({ success: true, data: { config: { marker: 'stale' }, rows: [], columns: [], count: 0 } });
    await Promise.all([oldCall, newCall]);
    expect(wrapper.vm.states.a.result.config.marker).not.toBe('stale');
    wrapper.unmount();
  });

  it('shows API errors on the dashboard and per component', async () => {
    api.queryReport.mockResolvedValueOnce({ success: false, message: '无查看权限' });
    const wrapper = mountDashboard(config()); await flushPromises();
    expect(wrapper.vm.states.a.error).toBe('无查看权限');
    expect(wrapper.text()).toContain('无查看权限');
    wrapper.unmount();
  });

  it('prevents row drill selection while configuration is dirty', async () => {
    const wrapper = mountDashboard(config()); await flushPromises();
    const before = api.queryReport.mock.calls.length;
    wrapper.vm.board.widgets[0].config.ordering = 'store_id';
    wrapper.vm.selectRow(wrapper.vm.board.widgets[0], { store_id: 'store-1' });
    expect(wrapper.vm.dirty).toBe(true);
    expect(wrapper.vm.link).toBeNull();
    expect(api.queryReport).toHaveBeenCalledTimes(before);
    wrapper.unmount();
  });

  it('does not restore a board containing a dataset outside the authorized list', async () => {
    const invalid = config('unknown');
    const wrapper = mountDashboard(invalid); await flushPromises();
    expect(wrapper.vm.board.widgets).toHaveLength(1);
    expect(wrapper.text()).toContain('无法访问的数据集');
    expect(api.queryReport).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('exports the exact queried component configuration and disables export when filters change', async () => {
    const wrapper = mountDashboard(config()); await flushPromises();
    wrapper.vm.board.filters.store_id = '2'; await wrapper.vm.run();
    await wrapper.get('button[aria-label="导出组件A"]').trigger('click'); await flushPromises();
    expect(api.createReportExport).toHaveBeenCalledWith({ report_type: 'self_service', filters: { config: expect.objectContaining({ filters: { store_id: '2' } }) } });
    expect(nav.push).toHaveBeenCalledWith('/reports/exports');
    wrapper.vm.board.filters.store_id = '3'; await flushPromises();
    expect(wrapper.get('button[aria-label="导出组件A"]').element.disabled).toBe(true);
    wrapper.unmount();
  });
  it('safely removes a component while its data request is pending', async () => {
    let complete;
    api.queryReport.mockImplementationOnce(cfg => new Promise(resolve => { complete = () => resolve(response(cfg)); }));
    const wrapper = mountDashboard(config()); await flushPromises();
    await wrapper.get('button[aria-label="移除组件A"]').trigger('click');
    complete(); await flushPromises();
    expect(wrapper.vm.board.widgets).toHaveLength(0);
    expect(wrapper.vm.states.a).toBeUndefined();
    wrapper.unmount();
  });
});
