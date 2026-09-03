import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  mockIntegrationWorkspace,
  mockSubjectApiAccess,
} from '../src/mock/integrations';

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

  it('guards subject API dialog reads, authorization, revoke and configuration navigation', () => {
    for (const permission of [
      'integrations.view',
      'integrations.store.authorize',
      'integrations.store.revoke',
      'integrations.run_live_readonly',
      'integrations.config.view',
      'integrations.credential.rotate',
    ]) expect(subjectAccessSource).toContain(`permission: '${permission}'`);
    expect(subjectAccessSource).toContain('if (!subjectViewAccess.value.allowed)');
    expect(subjectAccessSource).toContain('storeAuthorizeAccess.visible');
    expect(subjectAccessSource).toContain('storeAuthorizeAccess.disabled');
    expect(subjectAccessSource).toContain('storeRevokeAccess.visible');
    expect(subjectAccessSource).toContain('readonlyCheckAccess.visible');
    expect(subjectAccessSource).toContain('if (props.subjectType !== \'store\' || !storeAuthorizeAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (props.subjectType !== \'store\' || !storeRevokeAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (!readonlyCheckAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (!syncViewAccess.value.allowed)');
    expect(subjectAccessSource).toContain('if (!actionAccess.allowed)');
  });

  it('makes external readonly checks explicit and keeps sensitive actions recoverable', () => {
    expect(subjectAccessSource).toContain('平台只读检查');
    expect(subjectAccessSource).toContain('不会刷新或替换 Token');
    expect(subjectAccessSource).toContain('确认平台只读检查');
    expect(subjectAccessSource).toContain('撤销授权');
    expect(subjectAccessSource).toContain('确认撤销');
    expect(subjectAccessSource).toMatch(/async function checkToken\(binding\)[\s\S]*?finally \{\s+busy\.value = '';/);
    expect(subjectAccessSource).toMatch(/async function disableStoreBinding\(binding\)[\s\S]*?finally \{\s+busy\.value = '';/);
    expect(subjectAccessSource).toContain('credentialMaintenanceAccess');
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
