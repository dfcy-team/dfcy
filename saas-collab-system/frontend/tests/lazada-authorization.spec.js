import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Lazada platform and store authorization', () => {
  it('loads platform, API type, environment and region options from server reference data', () => {
    const source = read('src/views/integrations/IntegrationWorkspace.vue');

    expect(source).toContain('v-for="platform in referencePlatforms"');
    expect(source).toContain('v-for="option in configApiTypeOptions"');
    expect(source).toContain('v-for="option in referenceEnvironments"');
    expect(source).toContain("data.value.reference_options?.countries");
    expect(source).not.toContain('<el-option label="Lazada" value="lazada" />');
    expect(source).toContain("activeConfig?.platform === 'lazada'");
    expect(source).toContain("['app_key', 'app_secret', 'redirect_uri']");
  });

  it('allows Lazada store OAuth without exposing an advertising section', () => {
    const source = read('src/components/SubjectApiAccessDialog.vue');

    expect(source).toContain("['lazada', 'shopee', 'tiktok'].includes(platform)");
    expect(source).toContain("platform !== 'lazada'");
    expect(source).toContain("lazada: 'Lazada'");
    expect(source).toContain('response.data?.simulation_callback');
    expect(source).toContain('completeSyntheticStoreAuthorization');
  });
});
