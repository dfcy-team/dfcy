import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchSyncAlertIncidents: vi.fn(), fetchSyncAlertIncidentRetryPreview: vi.fn(), retrySyncAlertIncident: vi.fn(), actOnSyncAlertIncident: vi.fn() }));
const state = vi.hoisted(() => ({ query: {}, push: vi.fn(), replace: vi.fn(), confirm: vi.fn() }));
vi.mock('../src/api/integrations', () => api);
vi.mock('../src/api/systemAdmin', () => ({ fetchUsers: vi.fn() }));
vi.mock('../src/api/request', () => ({ useMock: true }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: code => ['integrations.view', 'integrations.run'].includes(code) }) }));
vi.mock('vue-router', () => ({ useRoute: () => state, useRouter: () => state }));
vi.mock('element-plus', async original => ({ ...(await original()), ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() }, ElMessageBox: { confirm: state.confirm } }));
import Incident from '../src/views/integrations/SyncIncidentList.vue';
const row = { id: 7, sync_job_id: 3, last_sync_run_id: 9 };
beforeEach(() => {
  vi.clearAllMocks(); state.query = { sync_job_id: '3' };
  api.fetchSyncAlertIncidents.mockResolvedValue({ success: true, data: [row, { id: 8, sync_job_id: 4 }] });
  api.fetchSyncAlertIncidentRetryPreview.mockResolvedValue({ success: true, data: { allowed: true, source_sync_run_id: 9 } });
  api.retrySyncAlertIncident.mockResolvedValue({ success: true, data: { run: { id: 11, sync_job_id: 3 } } });
  state.confirm.mockResolvedValue('confirm');
});
describe('incident links and controlled retry', () => {
  it('filters the complete authorized result without sending unsupported job parameters', async () => {
    const w = shallowMount(Incident); await flushPromises();
    expect(api.fetchSyncAlertIncidents).toHaveBeenCalledWith({ status: '' });
    expect(w.vm.rows.map(item => item.id)).toEqual([7]); w.unmount();
  });
  it('keeps the same idempotency key after an uncertain network failure', async () => {
    const w = shallowMount(Incident); await flushPromises(); w.vm.openIncident(row); await w.vm.previewRetry();
    api.retrySyncAlertIncident.mockRejectedValueOnce(new Error('network'));
    await w.vm.confirmRetry();
    api.fetchSyncAlertIncidentRetryPreview.mockResolvedValueOnce({ success: true, data: { allowed: true, source_sync_run_id: 11 } });
    await w.vm.previewRetry(); await w.vm.confirmRetry();
    expect(api.retrySyncAlertIncident.mock.calls[0]).toEqual(api.retrySyncAlertIncident.mock.calls[1]);
    expect(w.vm.latestRetryRun).toEqual({ id: 11, sync_job_id: 3 });
    w.vm.openRun(11, 3); expect(state.push).toHaveBeenCalledWith({ path: '/integrations/sync-runs', query: { detail: '11', sync_job_id: '3' } }); w.unmount();
  });
  it('locks repeated confirmation and cancels a request if selection changes while confirming', async () => {
    const w = shallowMount(Incident); await flushPromises(); w.vm.openIncident(row); await w.vm.previewRetry();
    let accept; state.confirm.mockImplementationOnce(() => new Promise(resolve => { accept = resolve; }));
    const pending = w.vm.confirmRetry(); await w.vm.confirmRetry();
    expect(state.confirm).toHaveBeenCalledTimes(1);
    w.vm.openIncident({ id: 8, sync_job_id: 4 }); accept('confirm'); await pending;
    expect(api.retrySyncAlertIncident).not.toHaveBeenCalled(); w.unmount();
  });
});
