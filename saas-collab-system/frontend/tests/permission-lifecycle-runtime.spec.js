import { describe, expect, it } from 'vitest';
import { canAccessMenuItem, canAccessPath, menuItems, flattenMenuItems } from '../src/router/menu';
import { buildMenuPermissionRegistry } from '../src/router/menuRegistry';

describe('permission lifecycle at navigation boundaries', () => {
  const item = flattenMenuItems(menuItems).find(row => row.path === '/system/users');
  const user = { user_type: 'internal', is_superuser: true };
  it('denies retired menus and actions even for a superuser', () => {
    expect(canAccessPath({ ...user, inactive_permission_codes: item.menuPermissions }, item.path)).toBe(false);
    expect(canAccessMenuItem({ ...user, inactive_permission_codes: item.permissions }, item)).toBe(false);
  });
  it('navigation hiding leaves authorized deep links usable', () => {
    const hidden = { ...user, hidden_menu_permission_codes: item.menuPermissions };
    expect(canAccessMenuItem(hidden, item)).toBe(false);
    expect(canAccessPath(hidden, item.path)).toBe(true);
  });
  it('changing a path or label preserves the explicit stable menu code', () => {
    const renamed = { ...item, path: '/system/member-directory', label: '人员管理' };
    expect(buildMenuPermissionRegistry([renamed]).map(row => row.code)).toEqual(item.menuPermissions);
  });
});
