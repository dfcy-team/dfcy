import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Marketplace OAuth frontend contract', () => {
  it('keeps action permissions exact and scoped independently', () => {
    const menu = read('src/router/menu.js');
    const page = read('src/views/integrations/MarketplaceOAuth.vue');
    for (const permission of [
      'integrations.store.authorize',
      'integrations.credential.rotate',
      'integrations.store.revoke',
      'integrations.store.retry'
    ]) {
      expect(menu).toContain(permission);
      expect(page).toContain(permission);
    }
    expect(page).toContain('canRunAction');
    expect(page).toContain('startPolling');
  });

  it('uses server authorization URLs and never persists callback secrets', () => {
    const page = read('src/views/integrations/MarketplaceOAuth.vue');
    expect(page).toContain('window.location.assign(response.data.authorization_url)');
    expect(page).not.toMatch(/localStorage|sessionStorage|authorization_url\s*=|state\s*=\s*route/);
    expect(page).not.toContain('credential_ciphertext');
  });

  it('keeps OAuth API calls inside the internal integration boundary', () => {
    const api = read('src/api/integrations.js');
    expect(api).toContain('/api/internal/integrations/store-authorizations/oauth/initiate/');
    expect(api).toContain('/api/internal/integrations/oauth-attempts/');
    expect(api).not.toMatch(/\/api\/(finance|rpa)\/|\/admin\//);
  });

  it('exposes stable error and offline states in the component', () => {
    const page = read('src/views/integrations/MarketplaceOAuth.vue');
    expect(page).toContain('formatApiError');
    expect(page).toContain("status: 'offline'");
    expect(page).toContain('v-if="errorMessage"');
    expect(page).toContain('aria-busy');
  });
});
