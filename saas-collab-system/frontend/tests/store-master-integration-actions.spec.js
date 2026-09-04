import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  mockIntegrationWorkspace,
  mockSubjectApiAccess,
  mockStartStoreAuthorizationOAuth,
  mockCompleteSyntheticStoreAuthorization,
  mockCheckIntegrationReadonlyConnection,
  mockStoreAuthorizations,
  mockCreateSyncJob,
} from '../src/mock/integrations';
import { masterDataMocks } from '../src/mock/masterData';

const source = readFileSync(resolve(process.cwd(), 'src/views/masterdata/StoreMasterList.vue'), 'utf8');
const subjectAccessSource = readFileSync(resolve(process.cwd(), 'src/components/SubjectApiAccessDialog.vue'), 'utf8');
const integrationsApiSource = readFileSync(resolve(process.cwd(), 'src/api/integrations.js'), 'utf8');
const integrationsMockSource = readFileSync(resolve(process.cwd(), 'src/mock/integrations.js'), 'utf8');

describe('店铺档案 API 接入操作闭环', () => {
  it('uses the least-privilege permissions for integration entry points', () => {
    expect(source).toContain("permission: 'integrations.view'");
    expect(source).toContain("permission: 'integrations.store.view'");
    expect(source).toContain("permission: 'integrations.store.authorize'");
    expect(source).toContain("permission: 'masterdata.manage'");
    expect(source).not.toContain('integrations.store.manage');
    expect(source).toContain('if (!storeViewAccess.value.allowed)');
    expect(source).toContain('function openApiAccess(row)');
    expect(source).toContain('function openCapabilityMatrix(row)');
  });

  it('guards subject API dialog reads, authorization, refresh, revoke and configuration navigation', () => {
    for (const permission of [
      'integrations.view',
      'integrations.store.authorize',
      'integrations.store.revoke',
      'integrations.run_live_readonly',
      'integrations.config.view',
      'integrations.credential.rotate',
    ]) expect(subjectAccessSource).toContain(`permission: '${permission}'`);
    expect(subjectAccessSource).toContain('if (!subjectViewAccess.value.allowed)');
    expect(subjectAccessSource).toContain("permission: 'integrations.store.view'");
    expect(subjectAccessSource).toContain('storeApiViewAccess');
    expect(subjectAccessSource).toContain('if (!storeApiViewAccess.value.allowed)');
    expect(subjectAccessSource).toContain('storeAuthorizeAccess.visible');
    expect(subjectAccessSource).toContain('storeAuthorizeAccess.disabled');
    expect(subjectAccessSource).toContain('storeRevokeAccess.visible');
    expect(subjectAccessSource).toContain('storeRefreshAccess.visible');
    expect(subjectAccessSource).toContain('readonlyCheckAccess.visible');
    expect(subjectAccessSource).toContain('if (props.subjectType !== \'store\' || !storeAuthorizeAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (props.subjectType !== \'store\' || !storeRevokeAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (props.subjectType !== \'store\' || !storeRefreshAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (!readonlyCheckAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (!syncViewAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (!actionAccess.allowed)');
  });

  it('sends the exact store authorization to readonly checks and never falls through to another store/config', () => {
    expect(subjectAccessSource).toContain('{ store_authorization_id: binding.id }');
    const passed = mockCheckIntegrationReadonlyConnection(1, { store_authorization_id: 201 });
    expect(passed).toMatchObject({ success: true, data: { store_authorization_id: 201, sync_job_id: 1 } });
    const wrongConfig = mockCheckIntegrationReadonlyConnection(2, { store_authorization_id: 201 });
    expect(wrongConfig).toMatchObject({ success: false, code: 'INVALID_STORE_AUTHORIZATION' });
  });

  it('completes explicit Mock OAuth through the synthetic callback contract without credentials', () => {
    const started = mockStartStoreAuthorizationOAuth({
      platform: 'shopee',
      integration_config_id: 1,
      store_id: 1,
      region: 'SG',
      scopes: ['shop.info', 'order.read'],
    });
    expect(started).toMatchObject({
      success: true,
      data: { authorization_url: expect.stringContaining('sandbox.example.invalid'), simulation_callback: expect.any(Object) },
    });
    const completed = mockCompleteSyntheticStoreAuthorization('shopee', started.data.simulation_callback);
    expect(completed).toMatchObject({ success: true, data: { simulation: true, external_api_called: false } });
    expect(JSON.stringify(completed)).not.toMatch(/"(?:access_token|refresh_token|client_secret|app_secret|partner_key|credential_ciphertext|token_id)"\s*:/i);
  });

  it('makes external readonly checks explicit and keeps sensitive actions recoverable', () => {
    expect(subjectAccessSource).toContain('平台只读检查');
    expect(subjectAccessSource).toContain('不会刷新或替换 Token');
    expect(subjectAccessSource).toContain('确认平台只读检查');
    expect(subjectAccessSource).toContain('撤销授权');
    expect(subjectAccessSource).toContain('确认撤销');
    expect(subjectAccessSource).toContain('确认刷新令牌');
    expect(subjectAccessSource).toContain('refreshStoreAuthorization(binding.id, { confirmed: true })');
    expect(subjectAccessSource).toMatch(/async function refreshStoreBinding\(binding\)[\s\S]*?finally \{\s+busy\.value = '';/);
    expect(subjectAccessSource).toMatch(/async function checkToken\(binding\)[\s\S]*?finally \{\s+busy\.value = '';/);
    expect(subjectAccessSource).toMatch(/async function disableStoreBinding\(binding\)[\s\S]*?finally \{\s+busy\.value = '';/);
    expect(subjectAccessSource).toContain('credentialMaintenanceAccess');
  });

  it('keeps the current store reachable from readonly-check failure to a scoped sync-job create action', () => {
    expect(subjectAccessSource).toContain("permission: 'integrations.manage'");
    expect(subjectAccessSource).toContain('storeSyncCreateAccess.visible');
    expect(subjectAccessSource).toContain('createStoreSyncJob(apiType, primaryBinding(apiType))');
    expect(subjectAccessSource).toContain('store_authorization_id: binding.id');
    expect(subjectAccessSource).toContain('确认创建同步任务');
    expect(subjectAccessSource).toContain('不会写入平台业务数据');
    expect(subjectAccessSource).toContain('storeSyncResourceType');
    expect(subjectAccessSource).toContain('storeSyncResourceOptions');
    expect(subjectAccessSource).toContain('当前平台没有已注册的只读同步资源');
    expect(subjectAccessSource).toContain("shopee: Object.freeze(['sales_order', 'refund_return'])");
    expect(subjectAccessSource).toContain("tiktok: Object.freeze(['sales_order', 'refund_return'])");
    expect(subjectAccessSource).toContain('lazada: Object.freeze([])');
    expect(subjectAccessSource).not.toContain("apiType === 'advertising' ? 'settlement_bill'");
    const response = mockCreateSyncJob({
      integration_config_id: 1,
      store_authorization_id: 201,
      resource_type: 'sales_order',
      schedule_type: 'manual',
    });
    expect(response).toMatchObject({ success: true, data: { idempotent: true } });
    expect(mockCreateSyncJob({
      integration_config_id: 1,
      store_authorization_id: 201,
      resource_type: 'refund_return',
      schedule_type: 'manual',
    })).toMatchObject({
      success: true,
      data: { resource_type: 'refund_return', selected_authorization_id: 201 },
    });
  });

  it('makes the Mock sync-job gate reject unsupported or mismatched resources', () => {
    expect(mockCreateSyncJob({
      integration_config_id: 1,
      store_authorization_id: 201,
      resource_type: 'settlement_bill',
      schedule_type: 'manual',
    })).toMatchObject({ success: false, code: 'UNSUPPORTED_RESOURCE' });
    expect(mockCreateSyncJob({
      integration_config_id: 1,
      store_authorization_id: 201,
      resource_type: 'inventory_snapshot',
      schedule_type: 'manual',
    })).toMatchObject({ success: false, code: 'UNSUPPORTED_RESOURCE' });
    expect(mockCreateSyncJob({
      integration_config_id: 3,
      store_authorization_id: 201,
      resource_type: 'sales_order',
      schedule_type: 'manual',
    })).toMatchObject({ success: false, code: 'INVALID_INTEGRATION_CONFIG' });
  });

  it('keeps the store master, site and subject fixtures on the same implemented Shopee identity', () => {
    const store = masterDataMocks.stores().data.results[0];
    const platform = masterDataMocks.platforms().data.results.find((item) => item.id === store.platform_id);
    const site = masterDataMocks.platformSites().data.results.find((item) => item.id === store.platform_site_id);
    const subject = mockSubjectApiAccess('store', store.id).data.subject;
    expect(store).toMatchObject({ platform_id: 3, platform_name: 'Shopee', platform_site_id: 101 });
    expect(platform).toMatchObject({ id: 3, code: 'shopee', platform_type: 'shopee', connector_status: 'ACTIVE' });
    expect(site).toMatchObject({ platform_id: 3, platform_code: 'shopee', platform_type: 'shopee' });
    expect(subject).toMatchObject({ id: store.id, platform: 'shopee', platform_name: 'Shopee' });
  });

  it('retains authorization history and exposes safe detail fields without raw credentials', () => {
    const statuses = mockStoreAuthorizations({ store_id: 1 }).data.results.map((row) => row.status);
    expect(statuses).toEqual(expect.arrayContaining(['active', 'pending', 'expired', 'revoked', 'error']));
    expect(subjectAccessSource).toContain('授权历史');
    expect(subjectAccessSource).toContain('查看详情');
    expect(subjectAccessSource).toContain('API 授权记录详情');
    for (const field of ['scopesLabel', 'expirationDate', 'errorLabel', 'credentialMaskLabel']) {
      expect(subjectAccessSource).toContain(field);
    }
    expect(subjectAccessSource).toContain('凭据原文、Token 和密钥不会返回或回显');
    expect(JSON.stringify(mockStoreAuthorizations({ store_id: 1 }))).not.toMatch(/"(?:access_token|refresh_token|client_secret|app_secret|partner_key|credential_ciphertext|token_id)"\s*:/i);
  });

  it('consolidates store authorization in the store master instead of a duplicate integration page', () => {
    const routerSource = readFileSync(resolve(process.cwd(), 'src/router/index.js'), 'utf8');
    const menuSource = readFileSync(resolve(process.cwd(), 'src/router/menu.js'), 'utf8');
    expect(source).toContain('选择已就绪配置并发起授权');
    expect(source).toContain('>API 接入</el-button>');
    expect(subjectAccessSource).toContain('access.value.subject.id');
    expect(subjectAccessSource).toContain('config.callback_url');
    expect(subjectAccessSource).toContain('config.scopes || []');
    expect(subjectAccessSource).toContain('!selectedConfig(apiType).oauth_ready');
    expect(subjectAccessSource).toContain('popup = window.open');
    expect(subjectAccessSource).toContain('navigator.clipboard');
    expect(subjectAccessSource).toContain('浏览器阻止了新窗口');
    expect(subjectAccessSource).toContain('授权地址未能自动复制');
    expect(integrationsApiSource).toContain('mutation: true');
    expect(integrationsApiSource).toContain('noMockFallback: true');
    expect(routerSource).toContain("{ path: 'integrations/authorizations', redirect: '/master-data/stores' }");
    expect(routerSource).not.toContain("import('../views/integrations/StoreAuthorizationList.vue')");
    expect(menuSource).not.toContain("label: '店铺授权'");
  });

  it('keeps capability editing read-only unless authorization is active', () => {
    expect(source).toContain("['active', 'authorized'].includes(selectedAuthorization.value?.status)");
    expect(source).toContain('只有有效授权（active/authorized）可以保存能力矩阵');
    expect(source).toContain(':disabled="!capabilityEditAllowed"');
    expect(source).toContain('if (!storeAuthorizeAccess.value.allowed)');
    expect(source).toContain('if (!selectedAuthorizationId.value)');
    expect(source).toContain('updateConnectionCapabilities(selectedAuthorizationId.value, payload)');
    expect(source).toMatch(/async function saveCapabilities\(\)[\s\S]*?finally \{\s+capabilitySaving\.value = false;/);
    expect(source).toContain('write_enabled: false');
  });

  it('protects store import and site-mapping writes while keeping preview/download readable', () => {
    expect(source).toContain('@click="openImportDialog"');
    expect(source).toContain('function openImportDialog()');
    expect(source).toContain('if (!masterDataManageAccess.value.allowed)');
    expect(source).toContain('应用选中的 exact 映射');
    expect(source).toContain(':disabled="migrationManageAccess.disabled || !selectedMigrationStoreIds.length"');
    expect(source).toMatch(/async function submitImport\(\)[\s\S]*?finally \{\s+importing\.value = false;/);
    expect(source).toContain('下载 CSV 导入模板');
    expect(source).toContain('站点映射预览');
  });

  it('uses a shaped subject-access mock so the store dialog can render its complete flow', () => {
    const response = mockSubjectApiAccess('store', 1);
    expect(response.success).toBe(true);
    expect(response.data.subject).toMatchObject({
      id: 1,
      code: 'demo-store-sg',
      country_code: 'SG',
      platform: 'shopee',
      platform_name: 'Shopee',
    });
    expect(response.data.api_types).toEqual(['marketplace', 'advertising']);
    expect(response.data.configs).toEqual(expect.arrayContaining([
      expect.objectContaining({
        platform: 'shopee',
        api_type: 'marketplace',
        regions: expect.arrayContaining(['SG']),
        oauth_ready: true,
      }),
    ]));
    expect(response.data.bindings).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: 201,
        integration_config_id: 1,
        api_type: 'marketplace',
        status: 'active',
        platform_store_id: 'masked-external-store-001',
      }),
    ]));
    expect(integrationsApiSource).toContain('mockSubjectApiAccess(subjectType, subjectId)');
    const subjectApiBlock = integrationsApiSource.slice(
      integrationsApiSource.indexOf('export const fetchSubjectApiAccess'),
      integrationsApiSource.indexOf('export const startStoreAuthorization'),
    );
    expect(subjectApiBlock).not.toContain('data: null');
  });

  it('returns non-empty config and run workspaces with selectable sites and redacted fixtures', () => {
    const configs = mockIntegrationWorkspace('configs');
    const runs = mockIntegrationWorkspace('sync-runs');
    expect(configs.data.results.length).toBeGreaterThan(0);
    expect(configs.data.results[0]).toMatchObject({
      platform: 'shopee',
      api_type: 'marketplace',
      regions: expect.arrayContaining(['SG']),
      credential_status: 'referenced',
    });
    expect(configs.data.reference_options.platforms).toEqual(expect.arrayContaining([
      expect.objectContaining({ value: 'shopee', enabled: true }),
      expect.objectContaining({ value: 'lazada', enabled: true }),
    ]));
    expect(configs.data.reference_options.countries).toEqual(expect.arrayContaining([
      expect.objectContaining({ country_code: 'SG' }),
      expect.objectContaining({ country_code: 'MY' }),
    ]));
    expect(configs.data.reference_options.environments).toEqual(expect.arrayContaining([
      expect.objectContaining({ value: 'sandbox' }),
      expect.objectContaining({ value: 'pilot' }),
      expect.objectContaining({ value: 'production' }),
    ]));
    expect(runs.data.results).toEqual(expect.arrayContaining([
      expect.objectContaining({ status: 'failed', execution_mode: 'simulation', external_api_called: false }),
      expect.objectContaining({ status: 'failed', execution_mode: 'live_readonly', external_api_called: true }),
    ]));
    expect(runs.data.pagination.total).toBe(runs.data.results.length);

    const configStart = integrationsMockSource.indexOf('const config = {');
    const configEnd = integrationsMockSource.indexOf('\n};', configStart);
    const configBlock = integrationsMockSource.slice(configStart, configEnd);
    const configKeys = [...configBlock.matchAll(/^\s{2}([A-Za-z_][A-Za-z0-9_]*):/gm)].map((match) => match[1]);
    expect(configKeys.length).toBe(new Set(configKeys).size);
    expect(JSON.stringify({ configs, runs, subject: mockSubjectApiAccess('store', 1) }))
      .not.toMatch(/"(?:access_token|refresh_token|client_secret|app_secret|partner_key|credential_ciphertext|token_id)"\s*:/i);
  });
});
