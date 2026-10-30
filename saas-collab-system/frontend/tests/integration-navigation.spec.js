import { describe, it, expect } from 'vitest';
import { buildIntegrationSidebar } from '../src/router/integrationNavigation';
import { canAccessPath, filterSidebarMenuItems, flattenMenuItems } from '../src/router/menu';

const admin = { user_type: 'internal', tenant_id: 1, is_superuser: true, permissions: [] };
const section = user => buildIntegrationSidebar(user).find(item => item.label === 'API数据接入');

describe('API access navigation presentation', () => {
  it('rejects legacy business grants regardless of individual validity', () => {
    const path = '/integrations/authorization-center';
    for (const code of ['integrations.store.view', 'integrations.warehouse.view']) {
      const user = { user_type: 'internal', permissions: [code], inactive_permission_codes: [code] };
      expect(canAccessPath(user, path)).toBe(false);
      expect(flattenMenuItems(buildIntegrationSidebar(user)).some(item => item.path === path)).toBe(false);
    }
    expect(canAccessPath({ user_type: 'internal', permissions: ['integrations.store.view', 'integrations.warehouse.view'], inactive_permission_codes: ['integrations.store.view'] }, path)).toBe(false);
  });
  it('groups the existing routes into six entries without orphaning old pages', () => {
    const result = section(admin);
    expect(result.children.map(item => item.label)).toEqual(['授权接入', '绑定与映射', '同步管理', '飞书协同', '内部系统接口', '接入设置']);
    const paths = new Set(flattenMenuItems([result]).map(item => item.path));
    const old = filterSidebarMenuItems(admin).find(item => item.label === 'API数据接入');
    for (const item of flattenMenuItems([old])) expect(paths.has(item.path)).toBe(true);
    expect(paths.has('/sales-management/data-quality')).toBe(true);
    expect(paths.has('/integrations/store-mappings')).toBe(true);
  });
  it('does not expose any navigation to anonymous users', () => {
    expect(buildIntegrationSidebar(null)).toEqual([]);
  });
  it('never adds an inaccessible page for limited roles', () => {
    for (const permissions of [['feishu.view'], ['integrations.view'], ['integrations.store_mapping.view'], ['masterdata.view']]) {
      const user = { user_type: 'internal', permissions };
      const node = section(user);
      for (const item of flattenMenuItems(node ? [node] : [])) expect(canAccessPath(user, item.path), item.path).toBe(true);
    }
  });
  it('keeps non-API modules identical and does not mutate the canonical menu', () => {
    const before = filterSidebarMenuItems(admin);
    const others = items => items.filter(item => item.label !== 'API数据接入');
    expect(others(buildIntegrationSidebar(admin))).toEqual(others(before));
    expect(filterSidebarMenuItems(admin)).toEqual(before);
  });
  it('does not grant internal-interface configuration from a view permission', () => {
    const user = { user_type: 'internal', permissions: ['integrations.view'] };
    expect(flattenMenuItems(buildIntegrationSidebar(user)).some(item => item.path === '/integrations/ai-open-api')).toBe(false);
  });
});
