import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { toRaw } from 'vue';

const api = vi.hoisted(() => ({ fetchReportDatasets: vi.fn(), queryReport: vi.fn(), saveReportView: vi.fn() }));
const auth = vi.hoisted(() => ({ currentUser: { permissions: ['reports.view'] }, hasPermission: () => true }));
const nav = vi.hoisted(() => ({ route: { query: {} }, push: vi.fn() }));
vi.mock('../src/api/reporting', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('../src/router/menu', () => ({ canAccessPath: () => true }));
vi.mock('vue-router', () => ({ useRoute: () => nav.route, useRouter: () => ({ push: nav.push }) }));

import ReportResult from '../src/views/reports/ReportResult.vue';
import ReportWorkbench from '../src/views/reports/ReportWorkbench.vue';
import { displayReportValue, reportError } from '../src/views/reports/reportDisplay';

const dataset = { id: 'sales', name: '销售报表', module: '销售', path: '/sales/orders', filters: ['store_id'], dimensions: [{ key: 'store_id', label: '店铺' }, { key: 'month', label: '月份' }], metrics: [{ key: 'revenue', label: '销售额' }], defaults: { dimensions: ['store_id'], metrics: ['revenue'] } };
const stubs = {
  'el-button': { props: ['disabled'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-select': { template: '<select><slot /></select>' }, 'el-option': true,
  'el-form': { template: '<form @submit.prevent="$emit(\'submit\')"><slot /></form>' }, 'el-form-item': { template: '<label><slot /></label>' },
  'el-tag': true, 'el-alert': true, 'el-empty': true, 'el-checkbox': true, 'el-dialog': true, 'el-input': true, 'el-date-picker': true,
  'el-table': { props: ['data'], template: '<div><slot v-for="row in data" :row="row" /></div>' },
  'el-table-column': { template: '<div><slot v-for="row in $parent.$props.data || []" :row="row" /></div>' },
  'el-pagination': true
};

describe('report experience boundaries', () => {
  beforeEach(() => {
    vi.clearAllMocks(); nav.route.query = {};
    api.fetchReportDatasets.mockResolvedValue({ success: true, data: { datasets: [dataset] } });
    api.queryReport.mockResolvedValue({ success: true, data: { config: {}, rows: [], columns: [], count: 0 } });
  });

  it('shows financial enum labels in Chinese while keeping source values for drill-through', async () => {
    const row = { fee_category: 'platform_fee', match_status: 'conflict', revenue: 18 };
    const financial = { ...dataset, dimensions: [{ key: 'fee_category', label: '费用分类' }, { key: 'match_status', label: '匹配状态' }] };
    const wrapper = mount(ReportResult, { props: { result: { rows: [row], columns: [], count: 1 }, config: { dimensions: ['fee_category', 'match_status'], metrics: ['revenue'], chart: 'card' }, dataset: financial }, global: { stubs } });
    expect(wrapper.text()).toContain('平台费用 · 匹配冲突');
    await wrapper.find('.metric-cards button').trigger('click');
    expect(toRaw(wrapper.emitted('drill')[0][0])).toBe(row);
    expect(row.match_status).toBe('conflict');
    expect(displayReportValue('order_only', 'match_status')).toBe('仅订单匹配');
    expect(reportError('DATA_SCOPE_INVALID: 当前数据范围无效')).toBe('当前数据范围无效');
    expect(reportError('API response does not match the required envelope.')).toMatch(/数据读取失败/);
    wrapper.unmount();
  });

  it('paginates report rows locally and preserves the original row for drill-through', async () => {
    const rows = Array.from({ length: 51 }, (_, i) => ({ store_id: `店铺${i + 1}`, revenue: i + 1 }));
    const wrapper = mount(ReportResult, { props: { result: { rows, columns: [{ key: 'store_id', label: '店铺' }], count: 51 }, config: { dimensions: ['store_id'], metrics: ['revenue'], chart: 'card', chart_metric: 'revenue' }, dataset, type: 'card' }, global: { stubs } });
    expect(wrapper.findAll('.metric-cards > button')).toHaveLength(50);
    expect(wrapper.text()).toContain('店铺1');
    wrapper.vm.page = 2;
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('.metric-cards > button')).toHaveLength(1);
    expect(wrapper.text()).toContain('店铺51');
    await wrapper.find('.metric-cards > button').trigger('click');
    expect(toRaw(wrapper.emitted('drill')[0][0])).toBe(rows[50]);
    expect(api.queryReport).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('limits a pivot page to 25 rows and 12 columns without another query', async () => {
    const rows = Array.from({ length: 26 }, (_, i) => Array.from({ length: 13 }, (_, j) => ({ store_id: `店铺${i + 1}`, month: `月份${j + 1}`, revenue: i + j })).flat()).flat();
    const wrapper = mount(ReportResult, { props: { result: { rows, columns: [], count: rows.length }, config: { dimensions: ['store_id', 'month'], metrics: ['revenue'], chart: 'pivot', chart_metric: 'revenue', field_layout: { columns: ['month'] } }, dataset, type: 'pivot' }, global: { stubs } });
    expect(wrapper.findAll('tbody tr')).toHaveLength(25);
    expect(wrapper.findAll('.pivot-table thead th')).toHaveLength(13);
    wrapper.vm.matrixRowPage = 2; wrapper.vm.matrixColumnPage = 2;
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('tbody tr')).toHaveLength(1);
    expect(wrapper.findAll('.pivot-table thead th')).toHaveLength(2);
    expect(wrapper.text()).toContain('店铺26');
    expect(wrapper.text()).toContain('月份13');
    expect(api.queryReport).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('starts with the designer closed; toggling and resetting filters only edits the draft', async () => {
    const wrapper = mount(ReportWorkbench, { props: { catalog: [dataset] }, global: { stubs } });
    await flushPromises();
    expect(api.fetchReportDatasets).not.toHaveBeenCalled();
    const initialQueries = api.queryReport.mock.calls.length;
    expect(wrapper.find('.analysis-designer').exists()).toBe(false);
    const toggle = wrapper.findAll('button').find(button => button.text() === '调整字段和图表');
    await toggle.trigger('click'); await flushPromises();
    expect(wrapper.find('.analysis-designer').exists()).toBe(true);
    wrapper.vm.config.filters.store_id = 'draft-store';
    await wrapper.findAll('button').find(button => button.text() === '重置筛选').trigger('click');
    expect(wrapper.vm.config.filters).toEqual({});
    expect(api.queryReport).toHaveBeenCalledTimes(initialQueries);
    await wrapper.findAll('button').find(button => button.text() === '收起字段和图表').trigger('click');
    expect(wrapper.find('.analysis-designer').exists()).toBe(false);
    expect(api.queryReport).toHaveBeenCalledTimes(initialQueries);
    wrapper.unmount();
  });
});
