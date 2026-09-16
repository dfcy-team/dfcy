import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Shopee root callback bridge', () => {
  for (const target of ['../deploy/pilot/application/nginx.conf', '../deploy/sandbox/application/nginx.conf']) {
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
