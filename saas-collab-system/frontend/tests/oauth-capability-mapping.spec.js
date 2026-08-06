import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import {
  normalizeOAuthCapability,
  oauthCapabilityDescription,
  oauthCapabilityLabel,
  oauthCapabilityTagType
} from '../src/utils/oauthCapability';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('OAuth capability mapping stays fail closed', () => {
  it('only promotes on exact backend-provided values', () => {
    expect(normalizeOAuthCapability('mock')).toBe('mock');
    expect(normalizeOAuthCapability('sandbox_verified')).toBe('sandbox_verified');
    expect(normalizeOAuthCapability('connected')).toBe('connected');
    for (const invalid of [undefined, null, '', 'degraded', 'fallback', 'pending', 'Sandbox_Verified', 'CONNECTED']) {
      expect(normalizeOAuthCapability(invalid)).toBe('mock');
    }
  });

  it('labels every level without inventing new ones', () => {
    expect(oauthCapabilityLabel('mock')).toBe('Synthetic (mock)');
    expect(oauthCapabilityLabel('sandbox_verified')).toBe('Sandbox verified');
    expect(oauthCapabilityLabel('connected')).toBe('Connected');
    expect(oauthCapabilityTagType('sandbox_verified')).toBe('warning');
    expect(oauthCapabilityDescription('mock')).toContain('no real platform request');
  });

  it('maps api_status through the capability utility and never stamps verified values locally', () => {
    const api = read('src/api/integrations.js');
    expect(api).toContain("import { normalizeOAuthCapability } from '../utils/oauthCapability'");
    expect(api).toContain('normalizeOAuthCapability(response.data.api_status)');
    expect(api).not.toContain('asMockStatus');
    expect(api).not.toMatch(/api_status: 'sandbox_verified'/);
    expect(api).not.toMatch(/api_status: 'connected'/);
    const mock = read('src/mock/integrations.js');
    expect(mock).toContain("api_status: 'mock'");
    expect(mock).not.toMatch(/api_status: '(sandbox_verified|connected)'/);
  });
});

const api = vi.hoisted(() => ({
  fetchMarketplaceOAuthTargets: vi.fn(),
  fetchMarketplaceOAuthAttempt: vi.fn(),
  initiateMarketplaceOAuth: vi.fn(),
  refreshMarketplaceAuthorization: vi.fn(),
  revokeMarketplaceAuthorization: vi.fn(),
  retryMarketplaceAuthorization: vi.fn()
}));

vi.mock('../src/api/integrations', () => ({ ...api }));
vi.mock('../src/utils/oauthNavigation', () => ({ navigateToOAuthAuthorization: vi.fn() }));
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

describe('Marketplace OAuth capability indicator', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    Object.values(api).forEach((mock) => mock.mockReset());
    api.fetchMarketplaceOAuthAttempt.mockResolvedValue({ success: true, data: { status: 'pending' } });
    api.initiateMarketplaceOAuth.mockResolvedValue({ success: true, data: { attempt_id: 21 } });
  });

  const mountWithStatus = async (apiStatus) => {
    api.fetchMarketplaceOAuthTargets.mockResolvedValue({
      success: true,
      data: {
        action: 'authorize',
        configs: [{ id: 1, platform: 'shopee', account_alias: 'demo' }],
        stores: [{ store_id: 2, platform: 'shopee', store_name: 'demo' }],
        api_status: apiStatus
      }
    });
    const auth = useAuthStore();
    auth.setCurrentUser({ user_type: 'internal', permissions: ['integrations.store.authorize'] });
    const wrapper = mount(MarketplaceOAuth, { global: { stubs } });
    await flushPromises();
    return wrapper;
  };

  it('renders the synthetic capability until the backend verifies the sandbox', async () => {
    const wrapper = await mountWithStatus('mock');
    expect(wrapper.text()).toContain('Synthetic (mock)');
    expect(wrapper.text()).toContain('no real platform request is sent');
    wrapper.unmount();
  });

  it('renders the sandbox_verified capability only from backend evidence', async () => {
    const wrapper = await mountWithStatus('sandbox_verified');
    expect(wrapper.text()).toContain('Sandbox verified');
    expect(wrapper.text()).toContain('Sandbox integration verified');
    expect(wrapper.text()).not.toContain('Synthetic (mock)');
    wrapper.unmount();
  });

  it('downgrades unknown capability values to mock instead of promoting', async () => {
    const wrapper = await mountWithStatus('connected-lite');
    expect(wrapper.text()).toContain('Synthetic (mock)');
    expect(wrapper.text()).not.toContain('Connected');
    wrapper.unmount();
  });
});
