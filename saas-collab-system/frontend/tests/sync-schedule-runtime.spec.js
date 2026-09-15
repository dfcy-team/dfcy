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
