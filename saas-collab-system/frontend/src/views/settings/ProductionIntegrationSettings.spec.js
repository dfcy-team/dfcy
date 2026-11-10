import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProductionIntegrationSettings from './ProductionIntegrationSettings.vue';

const { fetchSettings, createVersion, fetchRenewal, saveRenewal } = vi.hoisted(() => ({
  fetchSettings: vi.fn(),
  createVersion: vi.fn(),
  fetchRenewal: vi.fn(),
  saveRenewal: vi.fn()
}));

vi.mock('../../api/integrations', () => ({
  fetchProductionIntegrationSettings: fetchSettings,
  createProductionIntegrationSettingsVersion: createVersion,
  fetchProductionTikTokRenewalSelection: fetchRenewal,
  saveProductionTikTokRenewalSelection: saveRenewal,
  approveProductionIntegrationSettingsVersion: vi.fn(),
  rollbackProductionIntegrationSettingsVersion: vi.fn()
}));
vi.mock('../../stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => true })
}));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }));

const submitButton = (wrapper) => wrapper.findAll('button').find((button) => button.text().includes('提交待审批版本'));

describe('ProductionIntegrationSettings TikTok creator query bindings', () => {
  beforeEach(() => {
    fetchSettings.mockReset().mockResolvedValue({
      success: true,
      data: { effective_config: { platforms: { tiktok: {
        creator_query_bindings: [{ tenant_id: 1, store_code: 'TK1PH', region: 'PH', platform_store_id: '123', integration_config_id: 1 }]
      } } } }
    });
    createVersion.mockReset().mockResolvedValue({ success: true });
  });

  it('preserves loaded bindings when submitting a configuration version', async () => {
    const wrapper = mount(ProductionIntegrationSettings, { global: { stubs: { transition: false } } });
    await vi.waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    await wrapper.get('input[placeholder="填写本次配置变更原因（至少 5 个字符）"]').setValue('保留达人查询绑定');
    await submitButton(wrapper).trigger('click');
    await vi.waitFor(() => expect(createVersion).toHaveBeenCalled());

    expect(createVersion.mock.calls[0][0].value.platforms.tiktok.creator_query_bindings)
      .toEqual([{ tenant_id: 1, store_code: 'TK1PH', region: 'PH', platform_store_id: '123', integration_config_id: 1 }]);
  });

  it('submits an empty binding list when older config has no bindings', async () => {
    fetchSettings.mockResolvedValueOnce({ success: true, data: { effective_config: { platforms: { tiktok: {} } } } });
    const wrapper = mount(ProductionIntegrationSettings, { global: { stubs: { transition: false } } });
    await vi.waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    await submitButton(wrapper).trigger('click');
    await vi.waitFor(() => expect(createVersion).toHaveBeenCalled());

    expect(createVersion.mock.calls[0][0].value.platforms.tiktok.creator_query_bindings).toEqual([]);
  });

  it('saves newly authorized shops alongside selected historical shops using the loaded version numbers', async () => {
    fetchRenewal.mockResolvedValue({ success: true, data: {
      effective_version: 42, latest_version: 42, unavailable_binding_count: 0,
      shops: [
        { id: 3, store_code: 'TK-HISTORY', region: 'PH', historical: true, selected: false },
        { id: 7, store_code: 'TK-NEW', region: 'TH', historical: false, selected: false }
      ]
    } });
    saveRenewal.mockResolvedValue({ success: true, data: { version: { version: 43 } } });
    const wrapper = mount(ProductionIntegrationSettings, {
      global: { stubs: { transition: false, teleport: true, ElSelect: true, ElOption: true } }
    });
    await flushPromises();
    await wrapper.get('[data-testid="edit-tiktok-renewal"]').trigger('click');
    await flushPromises();
    await wrapper.findAll('button').find((button) => button.text().includes('勾选历史店铺')).trigger('click');
    await wrapper.findAll('label').find((label) => label.text().includes('TK-NEW')).get('input').setValue(true);
    await wrapper.get('[data-testid="save-tiktok-renewal"]').trigger('click');
    await flushPromises();

    expect(saveRenewal).toHaveBeenCalledWith({
      effective_version: 42, latest_version: 42, authorization_ids: [3, 7],
      change_reason: '调整 TikTok Shop 店铺自动续期绑定'
    });
    wrapper.unmount();
  });
});
