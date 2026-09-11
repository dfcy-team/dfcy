import { flushPromises, shallowMount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('../src/api/masterData', () => ({
  fetchCountrySites: vi.fn().mockResolvedValue({ success: true, data: { results: [] } }),
  fetchPlatforms: vi.fn().mockResolvedValue({ success: true, data: { results: [
    { id: 7, name: '极风平台', code: 'CUSTOM', platform_type: 'warehouse_third_party', status: 'active', connector_key: 'jifeng_wms' },
    { id: 8, name: 'Other', platform_type: 'warehouse_third_party', status: 'active', connector_key: '' },
  ] } }),
  fetchWarehouses: vi.fn(), createMasterData: vi.fn(), updateMasterData: vi.fn(),
  deleteMasterData: vi.fn(), updateMasterDataStatus: vi.fn(),
}));
vi.mock('../src/api/integrations', () => ({
  fetchIntegrationConfigs: vi.fn().mockResolvedValue({ success: true, data: { results: [
    { id: 12, platform: 'jifeng_wms', account_alias: '公共配置' },
  ] } }),
}));

import WarehouseMasterList from '../src/views/masterdata/WarehouseMasterList.vue';
import AdminResourcePage from '../src/components/AdminResourcePage.vue';
import { createMasterData, updateMasterData } from '../src/api/masterData';

describe('Jifeng warehouse form', () => {
  it('keeps the archive form free of API credentials and directs users to API access', async () => {
    const wrapper = shallowMount(WarehouseMasterList);
    await flushPromises();
    const fields = wrapper.findComponent(AdminResourcePage).props('formFields');
    expect(fields.some(field => field.key.startsWith('api_'))).toBe(false);
    const page = wrapper.findComponent(AdminResourcePage);
    expect(page.props('formNotice')).toContain('API 接入');
    const payload = { code: 'TEST', service_platform_id: 7, api_email: 'fake@example.test', api_token: 'test-token', api_integration_config_id: 12 };
    await page.props('createHandler')(payload);
    await page.props('editHandler')(9, payload);
    expect(createMasterData).toHaveBeenCalledWith('warehouses', { code: 'TEST', service_platform_id: 7 });
    expect(updateMasterData).toHaveBeenCalledWith('warehouses', 9, { code: 'TEST', service_platform_id: 7 });
  });
});
