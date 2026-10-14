import { describe, expect, it } from 'vitest';
import { canAccessPath, filterMenuItems, flattenMenuItems } from '../src/router/menu';
const visible = user => flattenMenuItems(filterMenuItems(user)).some(x => x.path === '/finance/analytics');
describe('财务分析菜单与报表权限一致', () => {
  it('财务权限单独不能进入报表，兼容旧权限载荷', () => {
    const user = { user_type:'internal', permissions:['finance.view'] };
    expect(visible(user)).toBe(false); expect(canAccessPath(user,'/finance/analytics')).toBe(false);
    user.permissions.push('reports.view');
    expect(visible(user)).toBe(true); expect(canAccessPath(user,'/finance/analytics')).toBe(true);
  });
  it('分离菜单授权仍要求报表权限，业务权限未自动扩张', () => {
    const user = { user_type:'internal', menu_permission_codes:['menu.finance.finance_analytics.view'], action_permission_codes:['finance.view'], permissions:[] };
    expect(visible(user)).toBe(false); expect(canAccessPath(user,'/finance/analytics')).toBe(false);
    user.action_permission_codes.push('reports.view');
    expect(visible(user)).toBe(true); expect(canAccessPath(user,'/finance/analytics')).toBe(true);
  });
});
