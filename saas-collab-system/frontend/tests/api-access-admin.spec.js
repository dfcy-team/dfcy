import { describe, expect, it } from 'vitest';
import { isApiAccessAdmin } from '../src/utils/apiAccessAdmin';
import { canAccessPath } from '../src/router/menu';
import { buildIntegrationSidebar } from '../src/router/integrationNavigation';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from '../src/stores/auth';
describe('tenant API administrators', () => {
  for (const role of ['administrator', 'admin', 'tech_admin', 'integration_admin']) {
    it(`${role} sees all API groups without individual action grants`, () => {
      const user = { user_type: 'internal', tenant_id: 1, roles: [role], permissions: [] };
      expect(isApiAccessAdmin(user)).toBe(true);
      expect(canAccessPath(user, '/integrations/production-settings')).toBe(false);
      expect(canAccessPath(user, '/integrations/platform-sites')).toBe(false);
      for (const path of ['/integrations/authorization-center', '/integrations/feishu', '/integrations/ai-open-api']) expect(canAccessPath(user, path)).toBe(true);
      expect(buildIntegrationSidebar(user).find(item => item.label === 'API数据接入').children.map(item => item.label)).toEqual(['授权接入', '绑定与映射', '同步管理', '飞书协同', '内部系统接口', '接入设置']);
      setActivePinia(createPinia()); const auth = useAuthStore(); auth.currentUser = user;
      expect(auth.hasPermission('integrations.store.authorize')).toBe(true);
      expect(auth.hasPermission('feishu.connection.manage')).toBe(true);
      expect(auth.hasAllDataScopeFor('integrations.view')).toBe(true);
      expect(auth.hasAllDataScopeFor('config.system.manage')).toBe(false);
      expect(auth.hasPermission('config.system.manage')).toBe(false);
    });
  }
  it('denies business users even with legacy detailed grants', () => {
    const user = { user_type:'internal', tenant_id:1, roles:['operator'], permissions:['integrations.view','integrations.store.view','feishu.view'] };
    expect(canAccessPath(user,'/integrations/authorization-center')).toBe(false);
    expect(buildIntegrationSidebar(user).some(item => item.label === 'API数据接入')).toBe(false);
    setActivePinia(createPinia()); const auth=useAuthStore();auth.currentUser=user;
    expect(auth.hasPermission('integrations.store.view')).toBe(false);
  });
  it('requires an internal identity and tenant context', () => {
    expect(isApiAccessAdmin({user_type:'external',tenant_id:1,roles:['admin']})).toBe(false);
    expect(isApiAccessAdmin({user_type:'internal',roles:['admin']})).toBe(false);
  });
});
