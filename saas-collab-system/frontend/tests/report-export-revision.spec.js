import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';

const api = vi.hoisted(() => ({
  fetchReportExports: vi.fn(), createReportExport: vi.fn(), downloadReportExport: vi.fn(), downloadReportFile: vi.fn()
}));
const auth = vi.hoisted(() => ({ currentUser: { permissions: ['reports.export', 'reports.download'] }, hasPermission(code) { return this.currentUser?.is_superuser || this.currentUser?.permissions?.includes(code); } }));
vi.mock('../src/api/reportExports', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));

import ReportExportCenter from '../src/views/reports/ReportExportCenter.vue';

const rows = [{ id: 'r1', report_type: 'self_service', status: 'completed', has_file: true, filename: 'result.csv', filters: { date_from: '2026-01-01', nested: { channel: 'web' } } }, { id: 'r2', report_type: 'legacy', status: 'completed', has_file: false, filters: {} }];
const stubs = {
  'el-button': { props: ['disabled'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-select': { template: '<select><slot /></select>' }, 'el-option': { template: '<option><slot /></option>' },
  'el-form': { template: '<form><slot /></form>' }, 'el-form-item': { template: '<label><slot /></label>' },
  'el-alert': { props: ['title'], template: '<div class="alert">{{title}}</div>' },
  'el-table': { props: ['data'], template: '<div><slot v-for="row in data" :row="row" /></div>' },
  'el-table-column': { template: '<div><slot v-for="row in $parent.$props.data || []" :row="row" /></div>' },
  'el-pagination': true
};
const mountPage = () => mount(ReportExportCenter, { global: { stubs } });

describe('ReportExportCenter', () => {
  beforeEach(() => { vi.clearAllMocks(); auth.currentUser = { permissions: ['reports.export', 'reports.download'] }; api.fetchReportExports.mockResolvedValue({ success: true, data: { count: rows.length, results: rows } }); api.createReportExport.mockResolvedValue({ success: true, message: 'queued' }); api.downloadReportExport.mockResolvedValue({ success: true, data: { download_reference: '/api/report/exports/r1/file/' } }); api.downloadReportFile.mockResolvedValue({ success: true }); });

  it('re-exports using the original report type and exact filters snapshot', async () => {
    const wrapper = mountPage(); await flushPromises();
    await wrapper.get('button').trigger('click'); // refresh
    const buttons = wrapper.findAll('button');
    await buttons.find(button => button.text() === '再次导出').trigger('click');
    expect(api.createReportExport).toHaveBeenCalledWith({ report_type: 'self_service', filters: rows[0].filters });
  });

  it('saves a real file only through the signed server reference', async () => {
    const wrapper = mountPage(); await flushPromises();
    const downloadButton = wrapper.findAll('button').find(button => button.text() === '下载文件');
    await downloadButton.trigger('click'); await flushPromises();
    expect(api.downloadReportExport).toHaveBeenCalledWith('r1');
    expect(api.downloadReportFile).toHaveBeenCalledWith('/api/report/exports/r1/file/', 'result.csv');
  });

  it('does not offer a working download for historical placeholders and gates actions by permission', async () => {
    const wrapper = mountPage(); await flushPromises();
    expect(wrapper.text()).toContain('历史记录（无文件）');
    expect(api.downloadReportExport).not.toHaveBeenCalled();
    wrapper.unmount(); auth.currentUser = { permissions: [] };
    const restricted = mountPage(); await flushPromises();
    expect(restricted.findAll('button').some(button => button.text() === '再次导出')).toBe(false);
    expect(restricted.findAll('button').some(button => button.text() === '下载文件')).toBe(false);
  });

  it('ignores stale list responses and surfaces the latest API error', async () => {
    let resolveFirst;
    api.fetchReportExports.mockResolvedValueOnce({ success: true, data: { count: 0, results: [] } }).mockReturnValueOnce(new Promise(resolve => { resolveFirst = resolve; })).mockResolvedValueOnce({ success: false, message: 'read failed' });
    const wrapper = mountPage();
    await flushPromises();
    const stale = wrapper.vm.load();
    const latest = wrapper.vm.load(); await latest; await flushPromises();
    resolveFirst({ success: true, data: { count: 1, results: [{ id: 'stale' }] } }); await stale; await flushPromises();
    expect(wrapper.text()).toContain('read failed');
    expect(wrapper.text()).not.toContain('stale');
  });
});
