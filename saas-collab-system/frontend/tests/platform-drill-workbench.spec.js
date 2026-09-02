import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  mockConnectionCapabilities,
  mockStartStoreAuthorizationOAuth,
  mockStoreAuthorizations,
} from '../src/mock/integrations';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('platform drill operation closure', () => {
  it('registers a permission-guarded menu and route', () => {
    const menu = read('src/router/menu.js');
    const router = read('src/router/index.js');
    expect(menu).toContain("path: '/integrations/platform-drill'");
    expect(menu).toContain("label: '平台操作演练'");
    expect(menu).toContain("permissions: ['integrations.view']");
    expect(router).toContain("import('../views/integrations/PlatformDrillWorkbench.vue')");
    expect(router).toContain("path: 'integrations/platform-drill'");
  });

  it('covers config, authorization, capability, job, run, and incident handling', () => {
    const page = read('src/views/integrations/PlatformDrillWorkbench.vue');
    for (const label of ['接入配置', '店铺授权', '只读能力矩阵', '同步任务', '运行结果', '异常处置']) {
      expect(page).toContain(label);
    }
    expect(page).toContain('闭环可验收');
    expect(page).toContain('blocked_reason');
    expect(page).toContain("router.push(`/integrations/sync-runs/${row.id}`)");
    expect(page).toContain("path: '/integrations/sync-jobs'");
  });

  it('uses existing authorization lifecycle endpoints with explicit confirmation', () => {
    const api = read('src/api/integrations.js');
    const page = read('src/views/integrations/PlatformDrillWorkbench.vue');
    expect(api).toContain('/store-authorizations/oauth/start/');
    expect(api).toContain('/refresh/`');
    expect(api).toContain('/revoke/`');
    expect(api).toContain("url: '/api/internal/integrations/sync-jobs/'");
    expect(page).toContain('确认发起授权');
    expect(page).toContain('{ confirmed: true }');
    expect(page).toContain('确认撤销');
    expect(page).toContain('创建只读任务');
    expect(page).toContain("is_enabled: false");
    expect(page).toContain("schedule_type: 'manual'");
    expect(page).toContain('integrations.store.authorize');
    expect(page).toContain('integrations.store.revoke');
  });

  it('never auto-opens the returned OAuth URL or enables a write capability', () => {
    const page = read('src/views/integrations/PlatformDrillWorkbench.vue');
    expect(page).toContain('OAuth 地址仅展示和复制，不会自动跳转');
    expect(page).not.toMatch(/window\.open|location\.(assign|replace)|window\.location/);
    expect(page).not.toContain('write_enabled: true');
    expect(page).toContain("item.write_enabled" );
    const oauth = mockStartStoreAuthorizationOAuth({ platform: 'shopee', store_id: 1 });
    expect(oauth.success).toBe(true);
    expect(oauth.data.auth_url).toContain('https://sandbox.example.invalid/');
  });

  it('provides a realistic Shopee sandbox reference without live writes', () => {
    const authorization = mockStoreAuthorizations({ platform: 'shopee' }).data.results[0];
    const capability = mockConnectionCapabilities(authorization.id).data.results[0];
    expect(authorization).toMatchObject({ platform: 'shopee', region: 'SG', status: 'active' });
    expect(capability).toMatchObject({ capability_code: 'ORDER', read_enabled: true, write_enabled: false });
  });
});
