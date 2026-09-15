import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ requestApi: vi.fn(), createSyncJob: vi.fn(), fetchIntegrationWorkspace: vi.fn(), retrySyncRun: vi.fn() }));
const navigation = vi.hoisted(() => ({ push: vi.fn(), query: { sync_job_id: '7' } }));
vi.mock('../src/api/request', () => ({ requestApi: api.requestApi }));
vi.mock('../src/api/integrations', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: navigation.query }), useRouter: () => navigation }));
import CreateSyncJob from '../src/components/CreateSyncJob.vue';
import SyncExecutionRecords from '../src/views/integrations/SyncExecutionRecords.vue';
const item = { platform: 'tiktok', config_name: 'Test', integration_config_id: 6, subject_type: 'store', authorization_id: 2, subject_name: 'Test shop', resource_type: 'sales_order', blockers: [], existing_job_id: null };
beforeEach(() => {
  vi.clearAllMocks();
  api.requestApi.mockResolvedValue({ success: true, data: { items: [item] } });
  api.createSyncJob.mockResolvedValue({ success: true, data: { id: 7 } });
  api.fetchIntegrationWorkspace.mockResolvedValue({ success: true, data: { results: [], options: {}, pagination: { page: 2, total: 80 } } });
});
it('preview and precheck never create, confirmation creates disabled manual only', async () => {
  const wrapper = shallowMount(CreateSyncJob);
  await flushPromises();
  wrapper.vm.configId = 6; wrapper.vm.subjectKey = 'store:2'; wrapper.vm.selected = item;
  await wrapper.vm.check();
  expect(api.createSyncJob).not.toHaveBeenCalled();
  await Promise.all([wrapper.vm.create(), wrapper.vm.create()]);
  expect(api.createSyncJob).toHaveBeenCalledTimes(1);
  expect(api.createSyncJob).toHaveBeenCalledWith({ integration_config_id: 6, store_authorization_id: 2, resource_type: 'sales_order', schedule_type: 'manual', is_enabled: false });
  expect(wrapper.emitted('created')).toEqual([[7]]);
});
it.each([{ existing_job_id: 7 }, { blockers: ['授权过期'] }])('blocks existing or unready creation: %j', async override => {
  const wrapper = shallowMount(CreateSyncJob); await flushPromises();
  wrapper.vm.selected = { ...item, ...override }; wrapper.vm.checked = true;
  await wrapper.vm.create(); expect(api.createSyncJob).not.toHaveBeenCalled();
});
it('records retain task filter and current page during refresh', async () => {
  const wrapper = shallowMount(SyncExecutionRecords); await flushPromises();
  await wrapper.vm.load();
  expect(api.fetchIntegrationWorkspace).toHaveBeenLastCalledWith('sync-runs', expect.objectContaining({ sync_job_id: '7', page: 2 }));
  expect(api.retrySyncRun).not.toHaveBeenCalled();
  wrapper.vm.task({ sync_job_id: 7 });
  expect(navigation.push).toHaveBeenCalledWith({ path: '/integrations/sync-jobs', query: { sync_job_id: '7' } });
});
