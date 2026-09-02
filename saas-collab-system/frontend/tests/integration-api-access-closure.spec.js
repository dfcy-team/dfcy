import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessPath, menuItems, routeCapabilities } from '../src/router/menu';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('API 数据接入生产页面闭环', () => {
  it('registers every integration operation page with precise view permissions', () => {
    const apiMenu = menuItems.find((item) => item.label === 'API数据接入');
    expect(apiMenu?.permissions).toEqual(expect.arrayContaining([
      'integrations.view', 'integrations.store.view', 'integrations.audit.view', 'masterdata.view'
    ]));
    const expected = {
      '/integrations/readiness': 'integrations.view',
      '/integrations/authorizations': 'integrations.store.view',
      '/integrations/capabilities': 'integrations.store.view',
      '/integrations/store-mappings': 'integrations.store.view',
      '/integrations/product-mappings': 'integrations.store.view',
      '/integrations/incidents': 'integrations.view',
      '/integrations/audit': 'integrations.audit.view',
      '/integrations/platform-sites': 'masterdata.view'
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
});
