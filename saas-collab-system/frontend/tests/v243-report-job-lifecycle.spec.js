import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, shallowMount } from '@vue/test-utils';

const api = vi.hoisted(() => ({ startAnalysisJob: vi.fn(), pollAnalysisJob: vi.fn(), cancelAnalysisJob: vi.fn() }));
vi.mock('../src/views/reports/periodAnalysis', async importOriginal => ({ ...(await importOriginal()), ...api }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: { is_superuser: true } }) }));
vi.mock('../src/router/menu', () => ({ canAccessPath: () => true }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));
import AnnualComparison from '../src/components/AnnualComparison.vue';
import InventoryPeriodComparison from '../src/components/inventory/InventoryPeriodComparison.vue';
import PeriodAnalysis from '../src/components/PeriodAnalysis.vue';

const wrappers = [];
const view = (component, props = {}) => {
  const wrapper = shallowMount(component, { props, global: { renderStubDefaultSlot: true, stubs: { 'el-table-column': { template: '<span />' } } } });
  wrappers.push(wrapper); return wrapper;
};
beforeEach(() => { vi.resetAllMocks(); api.cancelAnalysisJob.mockResolvedValue({ success: true, data: { status: 'cancelled' } }); });
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); });
const complete = result => ({ success: true, data: { id: 41, status: 'completed', result } });

describe.each([
  ['annual', AnnualComparison, { groups: [], snapshot_id: 'old' }, vm => { vm.filterCurrency = 'USD'; }],
  ['inventory', InventoryPeriodComparison, { rows: [], snapshot_id: 'old' }, vm => { vm.site = 'US'; }]
])('%s job identity', (_name, component, oldResult, changeFilters) => {
  it('cannot resurrect a completed old job after the next creation fails', async () => {
    api.startAnalysisJob.mockResolvedValueOnce(complete(oldResult)).mockResolvedValueOnce({ success: false, message: '暂时不可用' });
    const wrapper = view(component);
    await wrapper.vm.run();
    const applied = wrapper.vm.applied;
    expect(wrapper.vm.jobId).toBeNull();
    changeFilters(wrapper.vm);
    await wrapper.vm.run();
    await wrapper.vm.execute(false);
    expect(api.pollAnalysisJob).not.toHaveBeenCalled();
    expect(wrapper.vm.applied).toBe(applied);
    expect(wrapper.vm.result.snapshot_id).toBe('old');
    expect(wrapper.vm.blocked).toBe(true);
    expect(wrapper.vm.jobId).toBeNull();
  });

  it('binds a resumed pending job to its original filters, not the edited form', async () => {
    api.startAnalysisJob.mockResolvedValue({ success: true, data: { id: 42, status: 'queued' } });
    api.pollAnalysisJob.mockResolvedValueOnce({ success: false, message: '临时网络错误' }).mockResolvedValueOnce(complete(oldResult));
    const wrapper = view(component);
    const original = wrapper.vm.signature;
    await wrapper.vm.run();
    changeFilters(wrapper.vm);
    await wrapper.vm.execute(false);
    expect(api.pollAnalysisJob.mock.calls.map(call => call[0])).toEqual([42, 42]);
    expect(wrapper.vm.applied).toBe(original);
    expect(wrapper.vm.blocked).toBe(true);
    expect(wrapper.vm.jobId).toBeNull();
  });

  it('clears inaccessible or terminal jobs without relabelling older results', async () => {
    api.startAnalysisJob.mockResolvedValue({ success: true, data: { id: 43, status: 'queued' } });
    api.pollAnalysisJob.mockResolvedValue({ success: true, data: { status: 'expired' } });
    const wrapper = view(component); await wrapper.vm.run();
    expect(wrapper.vm.jobId).toBeNull();
    expect(wrapper.vm.blocked).toBe(true);
  });
});

describe('period analysis recovery', () => {
  it('retains the submitted snapshot across a transient error and edited filters', async () => {
    api.startAnalysisJob.mockResolvedValue({ success: true, data: { id: 51, status: 'queued' } });
    api.pollAnalysisJob.mockResolvedValueOnce({ success: false, message: '临时错误' }).mockResolvedValueOnce(complete({ series: [] }));
    const wrapper = view(PeriodAnalysis, { dataset: 'sales' });
    await wrapper.vm.run();
    const original = JSON.parse(JSON.stringify(wrapper.vm.pendingSnapshot));
    expect(original.dataset).toBe('sales');
    wrapper.vm.filters.currency = 'USD';
    await wrapper.vm.retryStatus();
    expect(wrapper.vm.appliedSnapshot).toEqual(original);
    expect(wrapper.vm.dirty).toBe(true);
    expect(wrapper.vm.canDrill).toBe(false);
  });

  it('keeps a real cancel action visible after polling times out', async () => {
    api.startAnalysisJob.mockResolvedValue({ success: true, data: { id: 52, status: 'queued' } });
    api.pollAnalysisJob.mockResolvedValue({ success: false, code: 'POLL_TIMEOUT', message: '任务仍在运行' });
    const wrapper = view(PeriodAnalysis, { dataset: 'sales' });
    await wrapper.vm.run(); await flushPromises();
    expect(wrapper.vm.loading).toBe(false);
    expect(wrapper.text()).toContain('取消任务');
    await wrapper.vm.cancel();
    expect(api.cancelAnalysisJob).toHaveBeenCalledWith(52);
    expect(wrapper.vm.activeJobId).toBe('');
  });

  it.each(['rejected', 'network'])('retains the job snapshot when cancellation fails (%s)', async failure => {
    api.startAnalysisJob.mockResolvedValue({ success: true, data: { id: 53, status: 'queued' } });
    api.pollAnalysisJob.mockResolvedValueOnce({ success: false, code: 'POLL_TIMEOUT' }).mockResolvedValueOnce(complete({ series: [] }));
    if (failure === 'network') api.cancelAnalysisJob.mockRejectedValue(new Error('network unavailable'));
    else api.cancelAnalysisJob.mockResolvedValue({ success: false, message: '取消失败' });
    const wrapper = view(PeriodAnalysis, { dataset: 'sales' });
    await wrapper.vm.run();
    const original = JSON.parse(JSON.stringify(wrapper.vm.pendingSnapshot));
    wrapper.vm.filters.currency = 'USD';
    await wrapper.vm.cancel();
    expect(wrapper.vm.activeJobId).toBe(53);
    expect(wrapper.vm.pendingSnapshot).toEqual(original);
    await wrapper.vm.retryStatus();
    expect(wrapper.vm.appliedSnapshot).toEqual(original);
    expect(wrapper.vm.dirty).toBe(true);
    expect(wrapper.vm.canDrill).toBe(false);
  });
});
