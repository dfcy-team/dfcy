import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const testDirectory = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(testDirectory, '..', path), 'utf8');

describe('real marketplace connection UI boundary', () => {
  it('places OAuth and authorization APIs under connection configuration', () => {
    const page = read('src/views/integrations/IntegrationConfigEditor.vue');
    const panel = read('src/components/MarketplaceAuthorizationPanel.vue');
    const api = read('src/api/integrations.js');

    expect(page).toContain('MarketplaceAuthorizationPanel');
    expect(panel).toContain('店铺授权');
    expect(api).toContain('/store-authorizations/oauth/start/');
    expect(api).toContain('/store-authorizations/${id}/refresh/');
    expect(api).toContain('/store-authorizations/${id}/revoke/');
  });

  it('keeps configuration secrets write-only and uses separate rotate and clear actions', () => {
    const editor = read('src/views/integrations/IntegrationConfigEditor.vue');
    const field = read('src/components/integrations/SecretField.vue');
    const api = read('src/api/integrations.js');

    expect(editor).toContain('SecretField');
    expect(editor).toContain("integrations.credential.clear");
    expect(field).toContain('********');
    expect(field).toContain('autocomplete="new-password"');
    expect(api).toContain('/credentials/rotate/');
    expect(api).toContain('/credentials/clear/');
    expect(api).toContain("'Idempotency-Key'");
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
    expect(panel).toContain("selectedConfig.value?.scopes || []");
    expect(panel).toContain('selectedConfig.value?.callback_url');
    expect(panel).toContain("['localhost', '127.0.0.1', '::1']");
  });

  it('exposes the required configuration list filters and safe status columns', () => {
    const list = read('src/views/integrations/IntegrationConfigList.vue');

    expect(list).toContain('filters.region');
    expect(list).toContain('filters.status');
    expect(list).toContain('credential_reference_version');
    expect(list).toContain('last_verified_at');
    expect(list).toContain('********');
  });
});
