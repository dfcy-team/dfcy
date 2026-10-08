import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import StoreMatrix from '../src/views/integrations/IntegrationCapabilityMatrix.vue';
import WarehouseMatrix from '../src/components/WarehouseCapabilityMatrix.vue';

const api = vi.hoisted(() => ({ fetchStoreAuthorizations: vi.fn(), fetchStoreAuthorizationDetail: vi.fn(), fetchStoreCapabilityMatrix: vi.fn(), updateStoreCapabilityMatrix: vi.fn(), checkIntegrationReadonlyConnection: vi.fn(), fetchWarehouseAuthorizations: vi.fn(), checkJifengWarehouse: vi.fn() }));
vi.mock('../src/api/integrations', () => api);
vi.mock('../src/api/request', () => ({ useMock: false }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }));
vi.mock('element-plus', async (importOriginal) => ({ ...(await importOriginal()), ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() }, ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) } }));
const stubs = { AppPage: { template: '<div><slot name="action"/><slot /></div>' }, WarehouseCapabilityMatrix: true, 'el-table': true, 'el-pagination': true, 'el-select': true, 'el-alert': true, 'el-radio-group': true };

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchStoreAuthorizations.mockResolvedValue({ success: true, data: { count: 1, results: [{ store_id: 1 }] } });
  api.fetchStoreCapabilityMatrix.mockResolvedValue({ success: true, data: { available_codes: ['ORDER'], results: [{ capability_code: 'ORDER', authorization_id: 7, read_enabled: true, status: 'active', sync_mode: 'realtime', execution_summary: { jobs_count: 2, enabled_jobs_count: 1, last_success_at: '2026-10-03T00:00:00Z' } }], authorizations: [{ id: 7, api_type: 'marketplace', status: 'active', integration_config_id: 3 }] } });
  api.checkIntegrationReadonlyConnection.mockResolvedValue({ success: true });
  api.fetchWarehouseAuthorizations.mockResolvedValue({ success: true, data: { count: 1, results: [{ id: 9, status: 'active', read_enabled: true, oauth_token_available: true }] } });
  api.checkJifengWarehouse.mockResolvedValue({ success: true });
});

describe('集中只读检查', () => {
  it('keeps sync mode as a read-only preference and clears source-specific execution facts on source change', async () => {
    const wrapper = mount(StoreMatrix, { global: { stubs } });
    await flushPromises();
    const row = wrapper.vm.capabilityRows[0];
    expect(row.sync_mode).toBe('realtime');
    expect(row.execution_summary).toMatchObject({ jobs_count: 2, enabled_jobs_count: 1, last_success_at: '2026-10-03T00:00:00Z' });
    wrapper.vm.onSourceChange(row);
    expect(row.execution_summary).toEqual({ jobs_count: 0, enabled_jobs_count: 0, last_success_at: null });
    const source = readFileSync(resolve(process.cwd(), 'src/views/integrations/IntegrationCapabilityMatrix.vue'), 'utf8');
    expect(source).toContain('（偏好）');
    expect(source).not.toContain('<el-option label="实时" value="realtime"');
    expect(source).toContain('实际执行');
  });

  it('uses the selected store resource and does not save capability edits', async () => {
    const wrapper = mount(StoreMatrix, { global: { stubs } });
    await flushPromises();
    await wrapper.vm.checkCapability(wrapper.vm.capabilityRows[0]);
    expect(api.checkIntegrationReadonlyConnection).toHaveBeenCalledWith(3, { store_authorization_id: 7, resource_type: 'sales_order' });
    expect(api.updateStoreCapabilityMatrix).not.toHaveBeenCalled();
  });
  it('does not call the API for a closed or unsupported capability', async () => {
    const wrapper = mount(StoreMatrix, { global: { stubs } });
    await flushPromises();
    await wrapper.vm.checkCapability({ capability_code: 'ORDER', read_enabled: false, status: 'active' });
    await wrapper.vm.checkCapability({ capability_code: 'ADVERTISING', read_enabled: true, status: 'active' });
    expect(api.checkIntegrationReadonlyConnection).not.toHaveBeenCalled();
  });
  it('checks a warehouse separately and reloads its saved metadata', async () => {
    const wrapper = mount(WarehouseMatrix, { global: { stubs } });
    await flushPromises();
    await wrapper.vm.check(wrapper.vm.rows[0]);
    expect(api.checkJifengWarehouse).toHaveBeenCalledWith(9);
    expect(api.fetchWarehouseAuthorizations).toHaveBeenCalledTimes(2);
    expect(api.updateStoreCapabilityMatrix).not.toHaveBeenCalled();
  });
});
