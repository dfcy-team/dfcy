import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetch: vi.fn(), execute: vi.fn(), confirm: vi.fn() }));
vi.mock('../src/api/advertising', () => ({ fetchLazadaAdvertising: api.fetch }));
vi.mock('../src/api/integrations', () => ({ executeLazadaRead: api.execute }));
vi.mock('element-plus', async importOriginal => ({ ...await importOriginal(), ElMessageBox: { confirm: api.confirm } }));
import Report from '../src/components/LazadaAdvertisingReport.vue';

const report = () => ({ success: true, data: { results: [], count: 0, summaries: [],
  stores: [{ store_id: 7, store__name: 'Lazada7', store__code: 'LZ7PH', authorization_id: 30 }] } });
beforeEach(() => {
  vi.clearAllMocks();
  api.fetch.mockResolvedValue(report()); api.confirm.mockResolvedValue('confirm');
  api.execute.mockResolvedValue({ success: true, data: { status: 'succeeded', days: 30, daily_sum: '13067.31', currency: 'PHP' } });
});

describe('Lazada persisted Sponsored Max report', () => {
  it('mount only queries persisted data, never synchronizes or refreshes', async () => {
    const wrapper = shallowMount(Report); await flushPromises();
    expect(api.fetch).toHaveBeenCalledTimes(1);
    expect(api.execute).not.toHaveBeenCalled();
    expect(api.fetch).toHaveBeenCalledWith(expect.objectContaining({ page: 1, page_size: 20 }));
    expect(wrapper.text()).toContain('不刷新授权'); wrapper.unmount();
  });
  it('collects only the explicitly selected authorization and dates after confirmation', async () => {
    const wrapper = shallowMount(Report); await flushPromises();
    wrapper.vm.storeId = 7; wrapper.vm.period = ['2026-09-01', '2026-09-30']; await flushPromises();
    await wrapper.vm.sync(); await flushPromises();
    expect(api.confirm).toHaveBeenCalledTimes(1);
    expect(api.execute).toHaveBeenCalledWith(30, { operation: 'smax_sync', payload: { startDate: '2026-09-01', endDate: '2026-09-30' } });
    expect(wrapper.vm.message).toContain('13067.31 PHP'); wrapper.unmount();
  });
  it('cancel and a missing synchronization grant never call the platform', async () => {
    const wrapper = shallowMount(Report); await flushPromises();
    await wrapper.vm.sync(); expect(api.execute).not.toHaveBeenCalled();
    wrapper.vm.storeId = 7; await flushPromises(); api.confirm.mockRejectedValueOnce('cancel');
    await wrapper.vm.sync(); expect(api.execute).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('shows failure instead of claiming success or falling back to demo spend', async () => {
    const wrapper = shallowMount(Report); await flushPromises();
    wrapper.vm.storeId = 7; await flushPromises();
    api.execute.mockResolvedValueOnce({ success: false, message: '授权已过期，不刷新' });
    await wrapper.vm.sync();
    expect(wrapper.vm.error).toContain('授权已过期'); expect(wrapper.vm.message).toBe(''); wrapper.unmount();
  });
  it('does not accept stale reports after changing the store', async () => {
    const wrapper = shallowMount(Report); await flushPromises();
    let resolve; api.fetch.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const pending = wrapper.vm.load(); wrapper.vm.storeId = 7; await flushPromises();
    resolve(report()); await pending;
    expect(wrapper.vm.report).toBe(null); wrapper.unmount();
  });
  it('validates date range before making any request', async () => {
    const wrapper = shallowMount(Report); await flushPromises(); api.fetch.mockClear();
    wrapper.vm.period = ['2026-09-01', '2026-10-02']; await flushPromises();
    await wrapper.vm.search();
    expect(api.fetch).not.toHaveBeenCalled(); expect(wrapper.vm.error).toContain('1～31'); wrapper.unmount();
  });
});
