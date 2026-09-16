import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const nginxTargets = ['../deploy/pilot/application/nginx.conf', '../deploy/sandbox/application/nginx.conf'];
const repositoryTemplatesAvailable = nginxTargets.every((target) => existsSync(resolve(process.cwd(), target)));

// The frontend production image intentionally receives only frontend and permission-registry files.
// Repository CI owns this cross-tree contract; the image build skips it when deploy templates are absent.
describe.runIf(repositoryTemplatesAvailable)('Shopee root callback bridge', () => {
  for (const target of nginxTargets) {
    it(`bridges only OAuth-shaped root callbacks in ${target}`, () => {
      const nginx = read(target);
      expect(nginx).toContain('map "$arg_code:$arg_error:$arg_state" $shopee_root_oauth_callback');
      expect(nginx).toContain('location = /');
      expect(nginx).toContain('if ($shopee_root_oauth_callback)');
      expect(nginx).toContain('rewrite ^ /api/internal/integrations/store-authorizations/oauth/callback/shopee/ last;');
      expect(nginx).toContain('try_files /index.html =404;');
    });
  }
});
