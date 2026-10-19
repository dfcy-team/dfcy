import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { reactive } from 'vue';
const api = vi.hoisted(() => ({ fetchAdsCapabilities: vi.fn(), updateAdsReadCapability: vi.fn(), createSyncJob: vi.fn() }));
const ui = vi.hoisted(() => ({ confirm: vi.fn(), push: vi.fn(), permissions: {} }));
vi.mock('../src/api/tiktokAds', () => api);
vi.mock('../src/api/integrations', () => ({ createSyncJob: api.createSyncJob }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: name => ui.permissions[name] !== false }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { store_id: '23' } }), useRouter: () => ({ push: ui.push }) }));
vi.mock('element-plus', async original => ({ ...(await original()), ElMessageBox: { confirm: ui.confirm }, ElMessage: { success: vi.fn() } }));
import Matrix from '../src/components/TikTokAdsCapabilityMatrix.vue';

const row = (extra = {}) => ({ mapping_id: 42, advertiser_id: '7365788829120397328', store_id: 23,
  store_code: 'TK1PH', store_name: 'Test shop', integration_config_id: 8, config_name: 'Test Ads',
  currency: 'PHP', timezone: 'Asia/Manila', read_enabled: false, can_enable_read: true,
  verification_state: 'verified', blocked_reason: '读取未开启', existing_job_id: null, ...extra });
beforeEach(() => {
  vi.clearAllMocks(); ui.permissions = reactive({});
  ui.confirm.mockResolvedValue(true);
  api.fetchAdsCapabilities.mockResolvedValue({ success: true, data: { items: [row(), row({ mapping_id: 43, advertiser_id: '7651940663654678546', currency: 'USD' })] } });
  api.updateAdsReadCapability.mockResolvedValue({ success: true });
  api.createSyncJob.mockResolvedValue({ success: true, data: { id: 99 } });
});
describe('TK Ads dedicated capability matrix', () => {
  it('only reads on mount and keeps both accounts separate', async () => {
    const wrapper = shallowMount(Matrix); await flushPromises();
    expect(wrapper.vm.visibleItems).toHaveLength(2);
    expect(wrapper.vm.stores).toHaveLength(1);
    expect(api.updateAdsReadCapability).not.toHaveBeenCalled();
    expect(api.createSyncJob).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('can turn on a verified disabled mapping without auto-enabling jobs', async () => {
    const wrapper = shallowMount(Matrix); await flushPromises();
    await wrapper.vm.setRead(row(), true);
    expect(api.updateAdsReadCapability).toHaveBeenCalledWith(42, true);
    expect(api.createSyncJob).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('refuses unready mappings and permission denial', async () => {
    const wrapper = shallowMount(Matrix); await flushPromises();
    await wrapper.vm.setRead(row({ can_enable_read: false }), true);
    ui.permissions['integrations.store.authorize'] = false; await flushPromises();
    await wrapper.vm.setRead(row(), true);
    expect(api.updateAdsReadCapability).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('allows disabling even after readiness has failed', async () => {
    const wrapper = shallowMount(Matrix); await flushPromises();
    await wrapper.vm.setRead(row({ read_enabled: true, can_enable_read: false }), false);
    expect(api.updateAdsReadCapability).toHaveBeenCalledWith(42, false); wrapper.unmount();
  });
  it('rechecks selected store after confirmation', async () => {
    let resolve; ui.confirm.mockReturnValue(new Promise(done => { resolve = done; }));
    const wrapper = shallowMount(Matrix); await flushPromises();
    const pending = wrapper.vm.setRead(row(), true); wrapper.vm.selectedStoreId = 88; resolve(true); await pending;
    expect(api.updateAdsReadCapability).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('does not optimistically change saved state on error', async () => {
    api.updateAdsReadCapability.mockRejectedValue(new Error('denied'));
    const wrapper = shallowMount(Matrix); await flushPromises();
    await wrapper.vm.setRead(wrapper.vm.visibleItems[0], true);
    expect(wrapper.vm.visibleItems[0].read_enabled).toBe(false);
    expect(wrapper.vm.error).toBeTruthy(); wrapper.unmount();
  });
  it('creates one ordinary manual disabled job for the selected advertiser', async () => {
    const wrapper = shallowMount(Matrix); await flushPromises();
    await wrapper.vm.createJob(row({ read_enabled: true, blocked_reason: '' }));
    expect(api.createSyncJob).toHaveBeenCalledWith({ integration_config_id: 8, ads_mapping_id: 42,
      resource_type: 'advertising_report', schedule_type: 'manual', is_enabled: false,
      execution_mode: 'live_readonly', query_mode: 'incremental', lookback_days: 7 });
    wrapper.vm.openJob(99);
    expect(ui.push).toHaveBeenCalledWith({ path: '/integrations/sync-jobs', query: { sync_job_id: 99 } }); wrapper.unmount();
  });
  it('does not create blocked/existing jobs or while permission revoked', async () => {
    const wrapper = shallowMount(Matrix); await flushPromises();
    await wrapper.vm.createJob(row());
    await wrapper.vm.createJob(row({ read_enabled: true, blocked_reason: '', existing_job_id: 99 }));
    ui.permissions['integrations.manage'] = false; await flushPromises();
    await wrapper.vm.createJob(row({ read_enabled: true, blocked_reason: '' }));
    expect(api.createSyncJob).not.toHaveBeenCalled(); wrapper.unmount();
  });
});
