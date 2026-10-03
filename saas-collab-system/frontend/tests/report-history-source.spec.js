import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const reporting = vi.hoisted(() => ({ fetchReportDatasets: vi.fn(), fetchSavedReportViews: vi.fn(), deleteReportView: vi.fn() }));
const collaboration = vi.hoisted(() => ({ fetchReportViewHistory: vi.fn(), fetchReportExceptionSource: vi.fn() }));
const workflow = vi.hoisted(() => ({ fetchWorkflowException: vi.fn(), assignWorkflowException: vi.fn(), closeWorkflowException: vi.fn(), resolveWorkflowException: vi.fn() }));
const auth = vi.hoisted(() => ({ currentUser: { user_id: 'u-1' }, hasPermission: () => true }));
const nav = vi.hoisted(() => ({ query: {}, params: { id: 'e-7' }, push: vi.fn() }));
vi.mock('../src/api/reporting', () => reporting);
vi.mock('../src/api/reportCollaboration', () => collaboration);
vi.mock('../src/api/workflow', () => workflow);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: nav.query, params: nav.params }), useRouter: () => ({ push: nav.push }) }));

import BasicReportIndex from '../src/views/reports/BasicReportIndex.vue';
import ExceptionDetail from '../src/views/workflow/ExceptionDetail.vue';

const config = { dataset: 'sales', dimensions: ['store_id'], metrics: ['revenue'], filters: {} };
const stubs = {
  'el-tabs': { template: '<div><slot /></div>' }, 'el-tab-pane': { template: '<section><slot /></section>' },
  'el-button': { props: ['disabled'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-tag': true, 'el-alert': true, 'el-empty': true, 'el-table': { props: ['data'], template: '<div><slot v-for="row in data" :row="row" /></div>' },
  'el-table-column': { props: ['label'], template: '<div><slot v-for="row in $parent.$props.data || []" :row="row" /></div>' },
  ReportWorkbench: { props: ['viewConfig', 'catalog'], template: '<div data-testid="workbench">{{ JSON.stringify(viewConfig) }}</div>' },
  ReportDashboard: { props: ['viewConfig'], template: '<div data-testid="dashboard">{{ JSON.stringify(viewConfig) }}</div>' },
  WorkflowDetailPage: { props: ['loader'], mounted() { this.loader(); }, template: '<div />' }
};

describe('report configuration history and source return', () => {
  beforeEach(() => {
    vi.clearAllMocks(); nav.query = {}; nav.params = { id: 'e-7' };
    reporting.fetchReportDatasets.mockResolvedValue({ success: true, data: { datasets: [], pending: [] } });
    collaboration.fetchReportExceptionSource.mockResolvedValue({ success: true, data: { source: { config } } });
  });

  it('loads the validated investigation config from the source API for a source_exception route', async () => {
    nav.query = { tab: 'analysis', dataset: 'sales', source_exception: 'e-7' };
    const wrapper = mount(BasicReportIndex, { global: { stubs } });
    await flushPromises();
    expect(collaboration.fetchReportExceptionSource).toHaveBeenCalledWith('e-7');
    expect(wrapper.get('[data-testid="workbench"]').text()).toContain('"dataset":"sales"');
    expect(wrapper.vm.sourceNotice).toContain('不是历史数据快照');
    wrapper.unmount();
  });

  it('does not load config or expose a retry entry when source validation fails', async () => {
    nav.query = { tab: 'analysis', source_exception: 'e-denied' };
    collaboration.fetchReportExceptionSource.mockResolvedValue({ success: false, message: 'forbidden' });
    const wrapper = mount(BasicReportIndex, { global: { stubs } });
    await flushPromises();
    expect(wrapper.vm.viewConfig).toBeNull();
    expect(wrapper.vm.tab).toBe('catalog');
    expect(wrapper.text()).not.toContain('重新查询');
    wrapper.unmount();
  });

  it('shows owner history with a Chinese baseline action and allows re-querying its config', async () => {
    nav.query = {};
    reporting.fetchReportDatasets.mockResolvedValue({ success: true, data: { datasets: [{ id: 'sales', name: '销售报表', dimensions: [{ key: 'store_id', label: '店铺' }], metrics: [{ key: 'revenue', label: '销售额' }] }], pending: [] } });
    reporting.fetchSavedReportViews.mockResolvedValue({ success: true, data: [{ id: 'v-1', is_owner: true, is_shared: true, name: '店铺销售', config, updated_at: '2026-01-01' }] });
    collaboration.fetchReportViewHistory.mockResolvedValue({ success: true, data: [{ version: 1, action: 'baseline', config, created_at: '2026-01-01' }] });
    const wrapper = mount(BasicReportIndex, { global: { stubs } });
    wrapper.vm.tab = 'saved';
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text() === '配置历史').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('迁移登记基线');
    expect(wrapper.text()).toContain('不是历史完整数据快照');
    expect(wrapper.text()).toContain('销售报表');
    expect(wrapper.text()).toContain('店铺');
    expect(wrapper.text()).toContain('销售额');
    expect(wrapper.text()).not.toContain('store_id');
    expect(wrapper.text()).not.toContain('revenue');
    await wrapper.findAll('button').find(button => button.text() === '按此配置重查').trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-testid="workbench"]').text()).toContain('store_id');
    wrapper.unmount();
  });

  it('uses the real report_group business_type and only offers a source return after validation', async () => {
    workflow.fetchWorkflowException.mockResolvedValue({ success: true, data: { id: 'e-7', business_type: 'report_group' } });
    collaboration.fetchReportExceptionSource.mockResolvedValue({ success: true, data: { source: { config } } });
    const wrapper = mount(ExceptionDetail, { global: { stubs } });
    await flushPromises();
    expect(wrapper.findAll('button').some(button => button.text() === '返回报表来源')).toBe(true);
    wrapper.unmount();
  });

  it('shows a Chinese source validation failure and hides the return entry', async () => {
    workflow.fetchWorkflowException.mockResolvedValue({ success: true, data: { id: 'e-7', business_type: 'report_group' } });
    collaboration.fetchReportExceptionSource.mockResolvedValue({ success: false, message: 'forbidden' });
    const wrapper = mount(ExceptionDetail, { global: { stubs } });
    await flushPromises();
    expect(wrapper.vm.sourceError).toContain('已隐藏回跳入口');
    expect(wrapper.findAll('button').some(button => button.text() === '返回报表来源')).toBe(false);
    wrapper.unmount();
  });

  it('reopens dashboard history in the dashboard view and localizes catalog field labels', async () => {
    const dashboardConfig = { kind: 'dashboard', module: '销售', widgets: [{ title: '收入', config: { dataset: 'sales', dimensions: ['store_id'], metrics: ['revenue'] } }] };
    const dashboard = { id: 'dashboard', name: '销售总览', is_owner: true, is_shared: true, config: dashboardConfig };
    reporting.fetchReportDatasets.mockResolvedValue({ success: true, data: { datasets: [{ id: 'sales', name: '销售报表', dimensions: [{ key: 'store_id', label: '店铺' }], metrics: [{ key: 'revenue', label: '销售额' }] }], pending: [] } });
    reporting.fetchSavedReportViews.mockResolvedValue({ success: true, data: [dashboard] });
    collaboration.fetchReportViewHistory.mockResolvedValue({ success: true, data: [{ version: 2, action: 'update', name: dashboard.name, config: dashboardConfig }] });
    const wrapper = mount(BasicReportIndex, { global: { stubs } });
    wrapper.vm.tab = 'saved';
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text() === '配置历史').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('销售 · 组合看板');
    expect(wrapper.text()).not.toContain('store_id');
    await wrapper.findAll('button').find(button => button.text() === '按此配置重查').trigger('click');
    await flushPromises();
    expect(wrapper.vm.tab).toBe('dashboard');
    expect(wrapper.get('[data-testid="dashboard"]').text()).toContain('"module":"销售"');
    wrapper.unmount();
  });
});
