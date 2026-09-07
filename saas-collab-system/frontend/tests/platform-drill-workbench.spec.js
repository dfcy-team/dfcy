import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  mockConnectionCapabilities,
  mockIntegrationWorkspace,
  mockStartStoreAuthorizationOAuth,
  mockStoreAuthorizations,
  mockWarehouseAuthorizations,
} from '../src/mock/integrations';
import { isWarehousePlatformDrillConfig, normalizePlatformDrillConfig } from '../src/views/integrations/platformDrillConfig';

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

  it('switches the authorization subject and master-data handoff for inventory configs', () => {
    const page = read('src/views/integrations/PlatformDrillWorkbench.vue');
    const masterData = read('src/mock/masterData.js');
    expect(page).toContain("isWarehouseConfig.value ? '仓库接入' : '店铺授权'");
    expect(page).toContain('选择仓库接入');
    expect(page).toContain('打开仓库 API 接入');
    expect(page).toContain("fetchWarehouseAuthorizations({ integration_config_id: config.id })");
    expect(page).toContain('subject-type="warehouse"');
    expect(page).toContain("router.push(isWarehouseConfig.value ? '/master-data/warehouses' : '/master-data/stores')");
    expect(page).toContain("integrations.warehouse.view");
    expect(masterData).toContain("service_platform_integration_key: 'jifeng_wms'");
    expect(masterData).toContain('api_access_available: true');
    expect(mockWarehouseAuthorizations({ integration_config_id: 3 }).data.results[0]).toMatchObject({
      integration_config_id: 3,
      warehouse_id: 1,
      status: 'active',
      provider: 'jifeng_wms',
    });
  });

  it('normalizes the production serializer shape before choosing warehouse authorization', () => {
    const collectionConfig = {
      id: 303,
      platform: 'jifeng_wms',
      account_alias: '极风 WMS · 生产',
      environment: 'production',
      platform_config: { api_type: 'inventory' },
    };
    const normalized = normalizePlatformDrillConfig(collectionConfig);

    expect(normalized.api_type).toBe('inventory');
    expect(isWarehousePlatformDrillConfig(normalized)).toBe(true);
    expect(normalized).not.toHaveProperty('subject_type', 'store');

    const detailOnlyType = normalizePlatformDrillConfig(
      { id: 304, platform: 'jifeng_wms', environment: 'production' },
      { id: 304, platform_config: { api_type: 'inventory' } },
    );
    expect(detailOnlyType.api_type).toBe('inventory');
    expect(normalizePlatformDrillConfig({ id: 305, platform: 'jifeng_wms' }).api_type).toBe('inventory');
    expect(read('src/views/integrations/PlatformDrillWorkbench.vue')).toContain('const detailResponse = await fetchIntegrationConfigDetail(configId);');
    expect(read('src/views/integrations/PlatformDrillWorkbench.vue')).toContain('fetchWarehouseAuthorizations({ integration_config_id: config.id })');
  });

  it('keeps warehouse lifecycle actions on the warehouse access dialog', () => {
    const page = read('src/views/integrations/PlatformDrillWorkbench.vue');
    const submitJob = page.match(/async function submitJob\(\)[\s\S]*?function goSubjectMasterData/)?.[0] || '';
    const refresh = page.match(/async function confirmRefresh\(row\)[\s\S]*?async function confirmRevoke/)?.[0] || '';
    const revoke = page.match(/async function confirmRevoke\(row\)[\s\S]*?function openJobDialog/)?.[0] || '';
    expect(submitJob).toContain('warehouse_authorization_id: selectedAuthorization.value.id');
    expect(submitJob).toContain('store_authorization_id: selectedAuthorization.value.id');
    expect(refresh).toContain('if (isWarehouseConfig.value) return;');
    expect(revoke).toContain('if (isWarehouseConfig.value) return;');
    expect(page).toContain('openWarehouseAccess(row)');
  });

  it('derives the warehouse read-only matrix from the selected authorization and links its inventory task precisely', () => {
    const page = read('src/views/integrations/PlatformDrillWorkbench.vue');
    const selection = page.match(/async function selectAuthorization\(row\)[\s\S]*?function isCompatibleWarehouse/)?.[0] || '';
    const warehouseMatrix = page.match(/const warehouseCapabilities = computed\(\(\) => \{[\s\S]*?\n\}\);/)?.[0] || '';
    expect(page).toContain('selectedInventoryTask');
    expect(page).toContain("job.resource_type === 'inventory_snapshot'");
    expect(page).toContain('job?.warehouse_authorization_id ?? job?.store_authorization_id ?? job?.selected_authorization_id');
    expect(page).toContain('displayCapabilities');
    expect(page).toContain('打开所选仓库 API 接入');
    expect(warehouseMatrix).toContain('read_enabled: true');
    expect(page).toContain("write_enabled: false");
    expect(warehouseMatrix).not.toContain('|| !task');
    expect(warehouseMatrix).not.toContain('task.is_enabled');
    expect(page).toContain('当前仓库：');
    expect(page).toContain('if (isWarehouseConfig.value) return;');
    expect(selection.indexOf('if (isWarehouseConfig.value) return;')).toBeLessThan(selection.indexOf('fetchConnectionCapabilities(row.id)'));

    const warehouseJobs = mockIntegrationWorkspace('sync-jobs', { platform: 'jifeng_wms' }).data.results;
    expect(warehouseJobs.find((job) => job.resource_type === 'inventory_snapshot')).toMatchObject({
      warehouse_authorization_id: 202,
      selected_authorization_id: 202,
      resource_type: 'inventory_snapshot',
    });
  });
});
