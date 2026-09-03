import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessPath, menuItems, routeCapabilities } from '../src/router/menu';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');

describe('API 数据接入生产页面闭环', () => {
  it('registers every integration operation page with precise view permissions', () => {
    const apiMenu = menuItems.find((item) => item.label === 'API数据接入');
    expect(apiMenu?.permissions).toEqual(expect.arrayContaining([
      'integrations.view', 'integrations.store.view', 'integrations.audit.view', 'integrations.config.view', 'masterdata.view'
    ]));
    const expected = {
      '/integrations/readiness': 'integrations.view',
      '/integrations/authorizations': 'integrations.store.view',
      '/integrations/capabilities': 'integrations.store.view',
      '/integrations/store-mappings': 'integrations.store.view',
      '/integrations/product-mappings': 'integrations.store.view',
      '/integrations/incidents': 'integrations.view',
      '/integrations/audit': 'integrations.audit.view',
      '/integrations/platform-sites': 'masterdata.view',
      '/integrations/configs': 'integrations.config.view'
    };
    for (const [pathName, permission] of Object.entries(expected)) {
      expect(apiMenu.children.find((item) => item.path === pathName)?.permissions).toEqual([permission]);
      expect(routeCapabilities.find((item) => item.path === pathName)?.permissions).toEqual([permission]);
    }
  });

  it('allows store-only and audit-only viewers to reach their pages without integrations.view', () => {
    const storeViewer = { user_type: 'internal', permissions: ['integrations.store.view'] };
    const auditViewer = { user_type: 'internal', permissions: ['integrations.audit.view'] };
    expect(canAccessPath(storeViewer, '/integrations/authorizations')).toBe(true);
    expect(canAccessPath(storeViewer, '/integrations/audit')).toBe(false);
    expect(canAccessPath(auditViewer, '/integrations/audit')).toBe(true);
    expect(canAccessPath(auditViewer, '/integrations/authorizations')).toBe(false);
  });

  it('uses the production endpoints and keeps dangerous actions explicit', () => {
    const api = read('src/api/integrations.js');
    expect(api).toContain("url: '/api/internal/integrations/store-mappings/'");
    expect(api).toContain("url: '/api/internal/integrations/product-mappings/'");
    expect(api).toContain("url: '/api/internal/integrations/audit/'");
    expect(api).toContain("url: '/api/internal/integrations/sync-alert-incidents/'");
    expect(read('src/views/integrations/StoreAuthorizationList.vue')).toContain('不会自动打开该地址');
    expect(read('src/views/integrations/IntegrationCapabilityMatrix.vue')).toContain('write_enabled: false');
    expect(read('src/views/integrations/SyncIncidentList.vue')).toContain('retrySyncAlertIncident');
    for (const file of ['StoreAuthorizationList.vue', 'IntegrationCapabilityMatrix.vue', 'StoreMappingList.vue', 'ProductMappingList.vue', 'SyncIncidentList.vue', 'IntegrationAuditList.vue']) {
      expect(read(`src/views/integrations/${file}`)).toContain('empty-text');
    }
  });

  it('keeps readiness follow-up links and contract repair confirmation dynamic', () => {
    const readiness = read('src/views/settings/PlatformIntegrationReadiness.vue');
    expect(readiness).toContain("path: '/integrations/authorizations'");
    expect(readiness).toContain('platform: row.platform_code');
    expect(readiness).not.toContain('授权 Shopee 店铺');
    expect(readiness).toContain('target_contract_version');
    expect(readiness).not.toContain('修复为 v2');
  });

  it('guards token refresh and capability writes by the current state', () => {
    const authorizations = read('src/views/integrations/StoreAuthorizationList.vue');
    expect(authorizations).toContain("route.query.platform");
    expect(authorizations).toContain('刷新令牌');
    expect(authorizations).toContain('撤销授权');
    expect(authorizations).toContain("auth.hasPermission('integrations.store.authorize') && auth.hasPermission('integrations.credential.rotate')");

    const capabilities = read('src/views/integrations/IntegrationCapabilityMatrix.vue');
    expect(capabilities).toContain("['active', 'authorized'].includes(selectedAuthorization.value?.status)");
    expect(capabilities).toContain('只有有效授权（active/authorized）可以保存能力矩阵');
    expect(capabilities).toContain('value="realtime"');
    expect(capabilities).toContain('value="webhook"');
    expect(capabilities).toContain('value="configured"');
    expect(capabilities).toContain('value="error"');

    const mockAuth = read('src/mock/auth.js');
    for (const permission of ['integrations.config.create', 'integrations.config.update', 'integrations.config.disable', 'integrations.run_live_readonly']) {
      expect(mockAuth).toContain(`'${permission}'`);
    }
  });

  it('clears async action state after API failures', () => {
    const authorizations = read('src/views/integrations/StoreAuthorizationList.vue');
    for (const functionName of ['load', 'openDetail', 'submitOAuth', 'refresh', 'revoke']) {
      expect(authorizations).toContain(`async function ${functionName}`);
    }
    expect((authorizations.match(/catch \(requestError\)/g) || []).length).toBeGreaterThanOrEqual(5);
    expect(authorizations).toContain('finally {\n    loading.value = false;\n  }');
    expect((authorizations.match(/finally \{\n    actionKey\.value = '';/g) || []).length).toBeGreaterThanOrEqual(3);
    expect(authorizations).toContain("response?.message || '授权地址生成失败。'");
    expect(authorizations).toContain("response?.message || '令牌刷新失败。'");
    expect(authorizations).toContain("response?.message || '授权撤销失败。'");

    const incidents = read('src/views/integrations/SyncIncidentList.vue');
    expect(incidents).toContain('async function load');
    expect(incidents).toContain('async function previewRetry');
    expect(incidents).toContain('async function confirmRetry');
    expect((incidents.match(/catch \(requestError\)/g) || []).length).toBeGreaterThanOrEqual(3);
    expect(incidents).toContain('finally {\n    loading.value = false;\n  }');
    expect((incidents.match(/finally \{\n    retryLoading\.value = false;/g) || []).length).toBeGreaterThanOrEqual(2);
    expect(incidents).toContain("response?.message || '重试预览失败。'");
    expect(incidents).toContain("response?.message || '受控重试失败。'");
  });

  it('documents mapping platform boundaries and closes incident/audit actions', () => {
    expect(read('src/views/integrations/StoreMappingList.vue')).toContain('Lazada 已支持授权但映射尚未开放');
    expect(read('src/views/integrations/ProductMappingList.vue')).toContain('Lazada 已支持授权但映射尚未开放');

    const incidents = read('src/views/integrations/SyncIncidentList.vue');
    expect(incidents).toContain("from '../../api/systemAdmin'");
    expect(incidents).toContain("fetchUsers({ page: 1, page_size: 100, status: 'active' })");
    expect(incidents).toContain("action === 'assign'");
    expect(incidents).toContain('assignee_id');
    expect(incidents).toContain('指派负责人');

    const audit = read('src/views/integrations/IntegrationAuditList.vue');
    expect(audit).toContain('查看详情');
    expect(audit).toContain('集成审计详情');
    expect(audit).toContain('selected.masked_detail');
    expect(read('src/mock/auth.js')).toContain('integrations.audit.view');
  });
});
