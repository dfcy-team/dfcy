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

describe('Jifeng warehouse form', () => {
  it('uses existing form components and shows credentials only for the canonical connector', async () => {
    const wrapper = shallowMount(WarehouseMasterList);
    await flushPromises();
    const fields = wrapper.findComponent(AdminResourcePage).props('formFields');
    const credentials = fields.filter(field => field.key.startsWith('api_'));
    expect(credentials.map(field => field.key)).toEqual([
      'api_integration_config_id', 'api_email', 'api_token', 'api_external_warehouse_code',
    ]);
    for (const field of credentials) {
      expect(field.label).toBeTruthy();
      expect(field.visible({ service_platform_id: 7 })).toBe(true);
      expect(field.visible({ service_platform_id: 8 })).toBe(false);
    }
    expect(credentials.find(field => field.key === 'api_token').type).toBe('password');
    expect(credentials.find(field => field.key === 'api_token').placeholder).toContain('留空保留');
    expect(credentials[0].options).toEqual([{ value: 12, label: '公共配置' }]);
  });
});
