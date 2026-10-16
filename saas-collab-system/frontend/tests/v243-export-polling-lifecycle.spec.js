import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, shallowMount } from '@vue/test-utils';

const api = vi.hoisted(() => ({ fetchReportExports: vi.fn(), fetchReportExportJobs: vi.fn(), fetchReportExportJob: vi.fn(), createReportExportJob: vi.fn(), cancelReportExportJob: vi.fn(), downloadReportExport: vi.fn(), downloadReportFile: vi.fn() }));
vi.mock('../src/api/reportExports', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: { permissions: ['reports.export'] } }) }));
import ReportExportCenter from '../src/views/reports/ReportExportCenter.vue';

let wrapper;
const pending = { id: 71, status: 'running', report_type: 'self_service' };
beforeEach(() => {
  vi.resetAllMocks(); vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  api.fetchReportExports.mockResolvedValue({ success: true, data: { count: 0, results: [] } });
  api.fetchReportExportJobs.mockResolvedValue({ success: true, data: [{ ...pending }] });
  api.fetchReportExportJob.mockResolvedValue({ success: true, data: { ...pending } });
});
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.useRealTimers(); });
async function mountPage() { wrapper = shallowMount(ReportExportCenter, { global: { renderStubDefaultSlot: true, stubs: { 'el-table-column': { template: '<span />' } } } }); await flushPromises(); return wrapper; }

describe('bounded export polling', () => {
  it.each([
    { success: false, http_status: 403, message: '禁止访问' },
    { success: false, code: 'PERMISSION_DENIED', message: '权限变更' }
  ])('stops immediately on authorization denial and leaves manual recovery available', async denied => {
    api.fetchReportExportJob.mockResolvedValue(denied);
    await mountPage();
    await vi.advanceTimersByTimeAsync(4000);
    await vi.advanceTimersByTimeAsync(600000);
    expect(api.fetchReportExportJob).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.exportJobs[0].status).toBe('running');
    expect(wrapper.text()).toContain('查询状态');
    expect(wrapper.vm.error).toContain('授权已变化');
    api.fetchReportExportJob.mockResolvedValue({ success: true, data: { ...pending } });
    await wrapper.vm.refreshJob(wrapper.vm.exportJobs[0]);
    await vi.advanceTimersByTimeAsync(4000);
    expect(api.fetchReportExportJob).toHaveBeenCalledTimes(3);
  });

  it('stops after three consecutive network failures, without faking a server status', async () => {
    api.fetchReportExportJob.mockRejectedValue(new Error('network unavailable'));
    await mountPage();
    await vi.advanceTimersByTimeAsync(12000);
    await vi.advanceTimersByTimeAsync(600000);
    expect(api.fetchReportExportJob).toHaveBeenCalledTimes(3);
    expect(wrapper.vm.exportJobs[0].status).toBe('running');
    expect(wrapper.vm.error).toContain('连续读取失败');
  });

  it('stops a continuously running job at five minutes and resumes only on manual action', async () => {
    await mountPage();
    await vi.advanceTimersByTimeAsync(600000);
    const calls = api.fetchReportExportJob.mock.calls.length;
    expect(calls).toBeGreaterThan(70); expect(calls).toBeLessThan(76);
    expect(wrapper.vm.error).toContain('自动检查已暂停');
    await wrapper.vm.refreshJobs();
    await vi.advanceTimersByTimeAsync(4000);
    expect(api.fetchReportExportJob).toHaveBeenCalledTimes(calls + 2);
  });

  it('does not overlap an unresolved request and does not restart after unmount', async () => {
    let resolve;
    api.fetchReportExportJob.mockReturnValue(new Promise(done => { resolve = done; }));
    await mountPage();
    await vi.advanceTimersByTimeAsync(4000);
    await vi.advanceTimersByTimeAsync(20000);
    expect(api.fetchReportExportJob).toHaveBeenCalledTimes(1);
    wrapper.unmount(); wrapper = null;
    resolve({ success: true, data: { ...pending } }); await flushPromises();
    await vi.advanceTimersByTimeAsync(600000);
    expect(api.fetchReportExportJob).toHaveBeenCalledTimes(1);
  });
});
