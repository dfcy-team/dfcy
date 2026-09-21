import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ requestApi: vi.fn(), updateSyncJob: vi.fn() }));
vi.mock('../src/api/request', () => ({ requestApi: api.requestApi }));
vi.mock('../src/api/integrations', () => ({ updateSyncJob: api.updateSyncJob }));
import SyncScheduleSettings from '../src/components/SyncScheduleSettings.vue';
beforeEach(() => {
  vi.clearAllMocks();
  api.requestApi.mockResolvedValue({ success: true, data: { times: ['2026-09-15T01:00:00Z'] } });
  api.updateSyncJob.mockResolvedValue({ success: true });
});
const mount = () => shallowMount(SyncScheduleSettings, { props: { canManage: true, job: { id: 7, is_enabled: false, schedule_type: 'daily' } } });
it('requires preview and saves without enabling or running', async () => {
  const wrapper = mount();
  await wrapper.vm.save();
  expect(api.updateSyncJob).not.toHaveBeenCalled();
  await wrapper.vm.preview();
  expect(api.updateSyncJob).not.toHaveBeenCalled();
  await wrapper.vm.save();
  expect(api.updateSyncJob).toHaveBeenCalledTimes(1);
  expect(api.updateSyncJob.mock.calls[0][1]).not.toHaveProperty('is_enabled');
  expect(wrapper.emitted('saved')).toHaveLength(1);
});
it('editing invalidates preview and blocks save', async () => {
  const wrapper = mount();
  await wrapper.vm.preview();
  wrapper.vm.form.local_time = '09:00';
  await flushPromises();
  await wrapper.vm.save();
  expect(api.updateSyncJob).not.toHaveBeenCalled();
});
it('readonly users cannot preview or save a schedule', async () => {
  const wrapper = mount();
  await wrapper.setProps({ canManage: false });
  await wrapper.vm.preview();
  await wrapper.vm.save();
  expect(api.requestApi).not.toHaveBeenCalled();
  expect(api.updateSyncJob).not.toHaveBeenCalled();
});
it('previews and saves collection range separately from schedule', async () => {
  const wrapper = mount();
  await wrapper.setProps({ job: { id: 10, is_enabled: false, platform: 'shopee', resource_type: 'refund_return', schedule_type: 'manual', lookback_days: 1 } });
  expect(wrapper.vm.form.lookback_days).toBe(1);
  wrapper.vm.form.lookback_days = 7;
  await flushPromises();
  await wrapper.vm.preview();
  await wrapper.vm.save();
  expect(api.updateSyncJob).toHaveBeenLastCalledWith(10, expect.objectContaining({ query_mode: 'incremental', lookback_days: 7, schedule_type: 'manual' }));
  wrapper.vm.form.query_mode = 'range';
  wrapper.vm.form.range_start_at = '2026-09-10';
  wrapper.vm.form.range_end_at = '2026-09-14';
  await flushPromises();
  expect(wrapper.vm.previewed).toBe(false);
  await wrapper.vm.preview();
  expect(api.requestApi.mock.lastCall[0].data.query_mode).toBe('range');
  expect(api.requestApi.mock.lastCall[0].data.range_end_at).toBe('2026-09-14');
});
it('displays existing timestamp ranges as Beijing dates', async () => {
  const wrapper = mount();
  await wrapper.setProps({ job: { id: 10, resource_type: 'refund_return', query_mode: 'range', range_start_at: '2026-09-09T16:00:00Z', range_end_at: '2026-09-14' } });
  expect(wrapper.vm.form.range_start_at).toBe('2026-09-10');
  expect(wrapper.vm.form.range_end_at).toBe('2026-09-14');
});
