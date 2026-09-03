import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Shopee production authorization guard', () => {
  it('allows the approved callback to be maintained without displaying secrets', () => {
    const workspace = read('src/views/integrations/IntegrationWorkspace.vue');

    expect(workspace).toContain("activeConfig?.platform === 'shopee'");
    expect(workspace).toContain('oauth/callback/shopee/');
    expect(workspace).toContain("['partner_id', 'partner_key', 'redirect_uri']");
    expect(workspace).toContain('type="password"');
    expect(workspace).toContain('secretCredentialFields');
  });

  it('does not call the OAuth start endpoint when the selected config is not ready', () => {
    const dialog = read('src/components/SubjectApiAccessDialog.vue');
    const guard = dialog.indexOf('if (!config.oauth_ready)');
    const request = dialog.indexOf('const response = await startStoreAuthorization');

    expect(dialog).toContain('oauthBlockerText');
    expect(dialog).toContain('Shopee 授权回调地址尚未配置');
    expect(dialog).toContain(':disabled="storeAuthorizeAccess.disabled || !selectedConfig(apiType) || !selectedConfig(apiType).oauth_ready"');
    expect(guard).toBeGreaterThan(-1);
    expect(request).toBeGreaterThan(guard);
  });
});
