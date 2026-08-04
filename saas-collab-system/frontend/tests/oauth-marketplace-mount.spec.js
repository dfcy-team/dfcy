import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const { fetchMarketplaceOAuthTargets } = vi.hoisted(() => ({
  fetchMarketplaceOAuthTargets: vi.fn()
}));

vi.mock('../src/api/integrations', () => ({
  fetchMarketplaceOAuthTargets,
  fetchMarketplaceOAuthAttempt: vi.fn(),
  initiateMarketplaceOAuth: vi.fn(),
  refreshMarketplaceAuthorization: vi.fn(),
  revokeMarketplaceAuthorization: vi.fn(),
  retryMarketplaceAuthorization: vi.fn()
}));

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
    : { action, authorizations: [] }
});

describe('Marketplace OAuth permission-scoped target view', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    fetchMarketplaceOAuthTargets.mockReset();
    fetchMarketplaceOAuthTargets.mockImplementation(async (action) => targetResponse(action));
  });

  it('mounts with authorize permission and loads only authorize targets', async () => {
    const auth = useAuthStore();
    auth.setCurrentUser({ user_type: 'internal', permissions: ['integrations.store.authorize'] });

    const wrapper = mount(MarketplaceOAuth, { global: { stubs } });
    await flushPromises();

    expect(fetchMarketplaceOAuthTargets).toHaveBeenCalledWith('authorize');
    expect(fetchMarketplaceOAuthTargets).not.toHaveBeenCalledWith('refresh');
    expect(wrapper.text()).toContain('Start authorization');
    expect(wrapper.text()).not.toContain('Refresh references');
  });

  it('mounts with action-only permission without requiring integrations.view', async () => {
    const auth = useAuthStore();
    auth.setCurrentUser({ user_type: 'internal', permissions: ['integrations.credential.rotate'] });

    const wrapper = mount(MarketplaceOAuth, { global: { stubs } });
    await flushPromises();

    expect(fetchMarketplaceOAuthTargets).toHaveBeenCalledWith('refresh');
    expect(wrapper.text()).toContain('Refresh references');
    expect(wrapper.findAll('button').map((button) => button.text())).not.toContain('Start authorization');
  });
});
