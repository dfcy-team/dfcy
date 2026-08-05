import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({
  fetchMarketplaceOAuthTargets: vi.fn(),
  fetchMarketplaceOAuthAttempt: vi.fn(),
  initiateMarketplaceOAuth: vi.fn(),
  refreshMarketplaceAuthorization: vi.fn(),
  revokeMarketplaceAuthorization: vi.fn(),
  retryMarketplaceAuthorization: vi.fn()
}));
const navigation = vi.hoisted(() => ({ navigateToOAuthAuthorization: vi.fn() }));

vi.mock('../src/api/integrations', () => ({
  ...api
}));

vi.mock('../src/utils/oauthNavigation', () => navigation);

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }));

import MarketplaceOAuth from '../src/views/integrations/MarketplaceOAuth.vue';
import { useAuthStore } from '../src/stores/auth';

const stubs = {
  'el-alert': { template: '<div><slot /></div>' },
  'el-card': { template: '<section><slot name="header" /><slot /></section>' },
  'el-descriptions': { template: '<div><slot /></div>' },
  'el-descriptions-item': { template: '<div><slot /></div>' },
  'el-empty': { template: '<div><slot /></div>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<div><slot /></div>' },
  'el-input': { template: '<input />' },
  'el-option': { template: '<option><slot /></option>' },
  'el-select': { template: '<select><slot /></select>' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-button': { template: '<button><slot /></button>' }
};

const targetResponse = (action) => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: action === 'authorize'
    ? {
        action,
        configs: [{ id: 1, platform: 'shopee', account_alias: 'demo' }],
        stores: [{ store_id: 2, platform: 'shopee', store_name: 'demo' }]
      }
    : {
        action,
        authorizations: [{
          id: action === 'refresh' ? 11 : action === 'revoke' ? 12 : 13,
          platform: 'shopee',
          store_name: 'demo',
          status: action === 'retry' ? 'error' : 'active'
        }]
      }
});

describe('Marketplace OAuth permission-scoped target view', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    Object.values(api).forEach((mock) => mock.mockReset());
    navigation.navigateToOAuthAuthorization.mockReset();
    api.fetchMarketplaceOAuthTargets.mockImplementation(async (action) => targetResponse(action));
    api.fetchMarketplaceOAuthAttempt.mockResolvedValue({ success: true, data: { status: 'pending' } });
    api.initiateMarketplaceOAuth.mockResolvedValue({
      success: true,
      data: { attempt_id: 21, authorization_url: 'https://synthetic.invalid/oauth/shopee/authorize' }
    });
    api.refreshMarketplaceAuthorization.mockResolvedValue({ success: true, data: { status: 'active' } });
    api.revokeMarketplaceAuthorization.mockResolvedValue({ success: true, data: { status: 'revoked' } });
    api.retryMarketplaceAuthorization.mockResolvedValue({
      success: true,
      data: { attempt_id: 22, status: 'initiated', authorization_url: 'https://synthetic.invalid/oauth/shopee/authorize' }
    });
  });

  it('mounts with authorize permission and loads only authorize targets', async () => {
    const auth = useAuthStore();
    auth.setCurrentUser({ user_type: 'internal', permissions: ['integrations.store.authorize'] });

    const wrapper = mount(MarketplaceOAuth, { global: { stubs } });
    await flushPromises();

    expect(api.fetchMarketplaceOAuthTargets).toHaveBeenCalledWith('authorize');
    expect(api.fetchMarketplaceOAuthTargets).not.toHaveBeenCalledWith('refresh');
    expect(wrapper.text()).toContain('Start authorization');
    expect(wrapper.text()).not.toContain('Refresh references');
    const startButton = wrapper.findAll('button').find((button) => button.text() === 'Start authorization');
    await startButton.trigger('click');
    await flushPromises();
    expect(api.initiateMarketplaceOAuth).toHaveBeenCalledOnce();
    expect(navigation.navigateToOAuthAuthorization).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it('mounts with action-only permission without requiring integrations.view', async () => {
    const auth = useAuthStore();
    auth.setCurrentUser({ user_type: 'internal', permissions: ['integrations.credential.rotate'] });

    const wrapper = mount(MarketplaceOAuth, { global: { stubs } });
    await flushPromises();

    expect(api.fetchMarketplaceOAuthTargets).toHaveBeenCalledWith('refresh');
    expect(wrapper.text()).toContain('Refresh references');
    expect(wrapper.findAll('button').map((button) => button.text())).not.toContain('Start authorization');
    const refreshButton = wrapper.findAll('button').find((button) => button.text() === 'Refresh references');
    await refreshButton.trigger('click');
    await flushPromises();
    expect(api.refreshMarketplaceAuthorization).toHaveBeenCalledWith('11', '');
    wrapper.unmount();
  });

  it('executes revoke-only action against its server-scoped target', async () => {
    const auth = useAuthStore();
    auth.setCurrentUser({ user_type: 'internal', permissions: ['integrations.store.revoke'] });
    const wrapper = mount(MarketplaceOAuth, { global: { stubs } });
    await flushPromises();
    const button = wrapper.findAll('button').find((item) => item.text() === 'Revoke authorization');
    await button.trigger('click');
    await flushPromises();
    expect(api.revokeMarketplaceAuthorization).toHaveBeenCalledWith('12', '');
    wrapper.unmount();
  });

  it('navigates retry-only user to the server authorization URL', async () => {
    const auth = useAuthStore();
    auth.setCurrentUser({ user_type: 'internal', permissions: ['integrations.store.retry'] });
    const wrapper = mount(MarketplaceOAuth, { global: { stubs } });
    await flushPromises();
    const button = wrapper.findAll('button').find((item) => item.text() === 'Retry failed authorization');
    await button.trigger('click');
    await flushPromises();
    expect(api.retryMarketplaceAuthorization).toHaveBeenCalledWith('13');
    expect(navigation.navigateToOAuthAuthorization).toHaveBeenCalledWith(
      'https://synthetic.invalid/oauth/shopee/authorize'
    );
    wrapper.unmount();
  });
});
