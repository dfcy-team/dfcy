import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const source = readFileSync(resolve(process.cwd(), 'src/views/integrations/IntegrationWorkspace.vue'), 'utf8');

describe('TikTok Shop registered callback configuration', () => {
  it('shows a labeled callback field in the Shop branch, separately from Ads', () => {
    const shop = source.split('<template v-else-if="activeConfig?.platform === \'tiktok\'">')[1].split('</template>')[0];
    expect(shop).toContain('label="授权回调地址"');
    expect(shop).toContain('v-model="credentialForm.redirect_uri"');
    expect(shop).toContain('type="url"');
    expect(shop).toContain('不是授权完成后带 code/state 的地址');
  });

  it('includes the registered callback in the Shop credential payload', () => {
    expect(source).toContain("['app_key', 'service_id', 'app_secret', 'redirect_uri']");
    expect(source).toContain("keys.filter(key => credentialForm[key] !== '')");
  });

  it('restores the saved non-secret address when reopening the editor', () => {
    const open = source.split('function openCredential(row) {')[1].split('\n}')[0];
    expect(open).toContain("credentialForm.redirect_uri = row.callback_url || ''");
    expect(open.indexOf('clearCredentialForm()')).toBeLessThan(open.indexOf('credentialForm.redirect_uri ='));
  });
});
