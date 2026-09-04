import { describe, expect, it } from 'vitest';
import { fetchAllPermissions } from '../src/api/systemAdmin';
import { canAccessPath, filterMenuItems, flattenMenuItems, menuItems } from '../src/router/menu';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('system administration tenant and permission surfaces', () => {
  it('loads the complete permission directory when it spans multiple pages', async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => ({ code: `action.${index}` }));
    const secondPage = Array.from({ length: 55 }, (_, index) => ({ code: `field.${index}` }));
    const calls = [];
    const result = await fetchAllPermissions(async (params) => {
      calls.push(params);
      return {
        success: true,
        data: {
          count: 155,
          next: params.page === 1 ? '/next' : null,
          results: params.page === 1 ? firstPage : secondPage,
        },
      };
    });

    expect(calls).toEqual([{ page: 1, page_size: 100 }, { page: 2, page_size: 100 }]);
    expect(result.rows).toHaveLength(155);
  });

  it('keeps tenant management superuser-only and uses categorized menu permissions first', () => {
    expect(menuItems.find((item) => item.label === '系统管理')).toBeTruthy();
    expect(canAccessPath({ user_type: 'internal', is_superuser: true }, '/system/tenants')).toBe(true);
    expect(canAccessPath({ user_type: 'internal', is_superuser: false, permissions: [] }, '/system/tenants')).toBe(false);
    expect(canAccessPath({ user_type: 'external', is_superuser: true }, '/system/tenants')).toBe(false);

    const categorizedUser = {
      user_type: 'internal',
      permissions: ['system.users.view'],
      menu_permission_codes: [],
      action_permission_codes: ['system.users.view'],
    };
    expect(flattenMenuItems(filterMenuItems(categorizedUser)).map((item) => item.path)).not.toContain('/system/users');
    expect(canAccessPath(categorizedUser, '/system/users')).toBe(true);
  });

  it('keeps the role page explicit about the target tenant and all three permission surfaces', () => {
    const source = read('src/views/system/RolePermissionMatrix.vue');
    expect(source).toContain('tenant_id');
    expect(source).toContain('目标租户');
    expect(source).toContain('menu_permission_codes');
    expect(source).toContain('action_permission_codes');
    expect(source).toContain('field_permission_codes');
    expect(source).toContain('fetchAllPermissions');
  });
});
