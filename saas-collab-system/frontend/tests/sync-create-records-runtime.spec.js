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
import { syncRuntimePresentation } from '../src/utils/syncPresentation';
const item = { platform: 'tiktok', config_name: 'Test', integration_config_id: 6, subject_type: 'store', subject_id: 3, authorization_id: 2, subject_name: 'Test shop', resource_type: 'sales_order', blockers: [], existing_job_id: null };
beforeEach(() => {
  vi.clearAllMocks();
  api.requestApi.mockResolvedValue({ success: true, data: { items: [item] } });
  api.createSyncJob.mockResolvedValue({ success: true, data: { id: 7 } });
  api.fetchIntegrationWorkspace.mockResolvedValue({ success: true, data: { results: [], options: {}, pagination: { page: 2, total: 80 } } });
});
it('preview and precheck never create, confirmation creates disabled manual only', async () => {
  const wrapper = shallowMount(CreateSyncJob);
  await flushPromises();
  wrapper.vm.subjectKey = 'store:3'; wrapper.vm.selectedResources = ['sales_order'];
  await wrapper.vm.check();
  expect(api.createSyncJob).not.toHaveBeenCalled();
  await Promise.all([wrapper.vm.create(), wrapper.vm.create()]);
  expect(api.createSyncJob).toHaveBeenCalledTimes(1);
  expect(api.createSyncJob).toHaveBeenCalledWith({ integration_config_id: 6, store_authorization_id: 2, resource_type: 'sales_order', schedule_type: 'manual', is_enabled: false });
  expect(wrapper.emitted('created')).toEqual([[{ count: 1, ids: [7] }]]);
});
it.each([{ existing_job_id: 7 }, { blockers: ['授权过期'] }])('blocks existing or unready creation: %j', async override => {
  api.requestApi.mockResolvedValue({ success: true, data: { items: [{ ...item, ...override }] } });
  const wrapper = shallowMount(CreateSyncJob); await flushPromises();
  wrapper.vm.subjectKey = 'store:3'; wrapper.vm.selectedResources = ['sales_order']; wrapper.vm.checked = true;
  await wrapper.vm.create(); expect(api.createSyncJob).not.toHaveBeenCalled();
});
it('creates multiple contents for one store with their own API sources', async () => {
  const product = { ...item, resource_type: 'platform_product' };
  const order = { ...item, resource_type: 'sales_order', config_name: 'Sales API', authorization_id: 4, integration_config_id: 9 };
  api.requestApi.mockResolvedValue({ success: true, data: { items: [product, order] } });
  api.createSyncJob.mockResolvedValueOnce({ success: true, data: { id: 7 } }).mockResolvedValueOnce({ success: true, data: { id: 8 } });
  const wrapper = shallowMount(CreateSyncJob); await flushPromises();
  expect(wrapper.vm.subjects).toHaveLength(1);
  wrapper.vm.subjectKey = 'store:3'; wrapper.vm.selectedResources = ['platform_product', 'sales_order'];
  await wrapper.vm.check();
  await wrapper.vm.create();
  expect(api.createSyncJob).toHaveBeenCalledTimes(2);
  expect(api.createSyncJob).toHaveBeenNthCalledWith(1, expect.objectContaining({ integration_config_id: 6, store_authorization_id: 2, resource_type: 'platform_product' }));
  expect(api.createSyncJob).toHaveBeenNthCalledWith(2, expect.objectContaining({ integration_config_id: 9, store_authorization_id: 4, resource_type: 'sales_order' }));
  expect(wrapper.emitted('created')).toEqual([[{ count: 2, ids: [7, 8] }]]);
});
it('requires an explicit API source when one store has multiple connections for a content', async () => {
  const other = { ...item, integration_config_id: 9, authorization_id: 4, config_name: 'Other API' };
  api.requestApi.mockResolvedValue({ success: true, data: { items: [item, other] } });
  const wrapper = shallowMount(CreateSyncJob); await flushPromises();
  wrapper.vm.subjectKey = 'store:3'; wrapper.vm.selectedResources = ['sales_order'];
  await wrapper.vm.check();
  expect(wrapper.vm.checked).toBe(false);
  expect(api.createSyncJob).not.toHaveBeenCalled();
  wrapper.vm.sourceIds.sales_order = 4;
  await wrapper.vm.check();
  expect(wrapper.vm.checked).toBe(true);
  await wrapper.vm.create();
  expect(api.createSyncJob).toHaveBeenCalledWith(expect.objectContaining({ integration_config_id: 9, store_authorization_id: 4 }));
});
it('records retain task filter and current page during refresh', async () => {
  const wrapper = shallowMount(SyncExecutionRecords); await flushPromises();
  await wrapper.vm.load();
  expect(api.fetchIntegrationWorkspace).toHaveBeenLastCalledWith('sync-runs', expect.objectContaining({ sync_job_id: '7', page: 2 }));
  expect(api.retrySyncRun).not.toHaveBeenCalled();
  wrapper.vm.task({ sync_job_id: 7 });
  expect(navigation.push).toHaveBeenCalledWith({ path: '/integrations/sync-jobs', query: { sync_job_id: '7' } });
});
it('shows latest runtime in routed records and separates continuation wait from original enqueue history', async () => {
  const row = {
    id: 22, sync_job_id: 7, status: 'running', enqueued_at: '2026-10-03T10:00:00Z', started_at: '2026-10-03T10:05:00Z',
    runtime_state: { state: 'queued', queued_since: '2026-10-04T01:00:00Z', wait_seconds: 18, last_progress_at: '2026-10-04T01:02:00Z', delivery_state: 'absent' }
  };
  api.fetchIntegrationWorkspace.mockResolvedValue({ success: true, data: { results: [row], options: {}, pagination: { page: 1, total: 1 } } });
  const wrapper = shallowMount(SyncExecutionRecords); await flushPromises();
  expect(syncRuntimePresentation(row.runtime_state)).toContain('当前等待 18 秒');
  expect(syncRuntimePresentation(row.runtime_state)).toContain('最近进度');
  wrapper.vm.open(row); await flushPromises();
  expect(wrapper.vm.detail.runtime_state.wait_seconds).toBe(18);
  expect(wrapper.vm.detail.enqueued_at).toBe('2026-10-03T10:00:00Z');
});
