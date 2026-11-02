import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProductionIntegrationSettings from './ProductionIntegrationSettings.vue';

const { fetchSettings, createVersion } = vi.hoisted(() => ({
  fetchSettings: vi.fn(),
  createVersion: vi.fn()
}));

vi.mock('../../api/integrations', () => ({
  fetchProductionIntegrationSettings: fetchSettings,
  createProductionIntegrationSettingsVersion: createVersion,
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
        creator_query_bindings: { creator_profile: { endpoint: '/creator/profile', query_key: 'handle' } }
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
      .toEqual({ creator_profile: { endpoint: '/creator/profile', query_key: 'handle' } });
  });

  it('submits an empty binding map when older config has no bindings', async () => {
    fetchSettings.mockResolvedValueOnce({ success: true, data: { effective_config: { platforms: { tiktok: {} } } } });
    const wrapper = mount(ProductionIntegrationSettings, { global: { stubs: { transition: false } } });
    await vi.waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    await submitButton(wrapper).trigger('click');
    await vi.waitFor(() => expect(createVersion).toHaveBeenCalled());

    expect(createVersion.mock.calls[0][0].value.platforms.tiktok.creator_query_bindings).toEqual({});
  });
});
