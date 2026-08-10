import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const testDirectory = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(testDirectory, '..', path), 'utf8');

describe('real marketplace connection UI boundary', () => {
  it('places OAuth and authorization APIs under connection configuration', () => {
    const page = read('src/views/integrations/IntegrationConfigList.vue');
    const panel = read('src/components/MarketplaceAuthorizationPanel.vue');
    const api = read('src/api/integrations.js');

    expect(page).toContain('MarketplaceAuthorizationPanel');
    expect(panel).toContain('店铺授权');
    expect(api).toContain('/store-authorizations/oauth/start/');
    expect(api).toContain('/store-authorizations/${id}/refresh/');
    expect(api).toContain('/store-authorizations/${id}/revoke/');
  });

  it('uses exact permissions and never renders raw credential inputs', () => {
    const panel = read('src/components/MarketplaceAuthorizationPanel.vue');
    expect(panel).toContain("integrations.store.authorize");
    expect(panel).toContain("integrations.credential.rotate");
    expect(panel).toContain("integrations.store.revoke");
    expect(panel).not.toMatch(/v-model="form\.(access_token|refresh_token|app_secret)"/);
    expect(panel).toContain('credentialMask(row.credential_mask)');
  });

  it('keeps supported pilot regions and provider callbacks separate', () => {
    const panel = read('src/components/MarketplaceAuthorizationPanel.vue');
    expect(panel).toContain("value: 'PH'");
    expect(panel).toContain("value: 'TH'");
    expect(panel).toContain("value: 'MY'");
    expect(panel).toContain('/oauth/callback/shopee/');
    expect(panel).toContain('/oauth/callback/tiktok/');
  });
});
