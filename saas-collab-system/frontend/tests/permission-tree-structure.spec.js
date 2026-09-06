import { describe, expect, it } from 'vitest';
import { buildPermissionTree, permissionModuleFromCode } from '../src/utils/permissionTree';
import { canAccessPath, filterMenuItems, menuPermissionRegistry } from '../src/router/menu';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('角色权限模块树', () => {
  it('按左侧菜单将模块分组，并把未知模块放入其他模块', () => {
    const tree = buildPermissionTree({
      menuItems: [
        { label: '产品开发', permissions: ['development.project.view'], children: [{ label: '新品市调', permissions: ['products.research.view'] }] },
        { label: '系统管理', children: [{ label: '角色权限', permissions: ['menu.system.roles.view'] }] },
      ], modules: ['development', 'products', 'system', 'new_module'],
    });
    expect(tree.map((item) => item.label)).toEqual(['产品开发', '系统管理', '其他模块']);
    expect(tree[0].children.map((item) => item.module)).toEqual(['development', 'products']);
    expect(tree[1].children[0]).toMatchObject({ module: 'system', label: '系统管理' });
    expect(tree[2].children[0]).toMatchObject({ module: 'new_module', label: '其他模块' });
    expect(permissionModuleFromCode('menu.system.roles.view')).toBe('system');
    expect(permissionModuleFromCode('field.system.users.name.view')).toBe('system');
  });

  it('同一模块出现在多个菜单时归入关联项更多的一级菜单', () => {
    const tree = buildPermissionTree({
      menuItems: [
        { label: '基础档案', children: [{ permissions: ['integrations.store_mapping.view'] }] },
        { label: 'API数据接入', children: [{ permissions: ['integrations.view', 'integrations.config.view'] }, { permissions: ['integrations.audit.view'] }] },
      ], modules: ['integrations'],
    });
    expect(tree).toHaveLength(1);
    expect(tree[0].label).toBe('API数据接入');
  });

  it('菜单登记源为每个页面生成稳定菜单权限码，并把菜单与操作权限分开校验', () => {
    expect(menuPermissionRegistry.length).toBeGreaterThan(50);
    expect(menuPermissionRegistry.every((item) => item.permission_type === 'menu' && item.code.startsWith('menu.') && item.metadata?.path && item.metadata?.status === 'active')).toBe(true);
    const productionPath = '/integrations/production-settings';
    const productionMenu = menuPermissionRegistry.find((item) => item.metadata.path === productionPath);
    expect(productionMenu).toBeTruthy();
    const menuOnlyUser = { user_type: 'internal', menu_permission_codes: [productionMenu.code], action_permission_codes: ['config.view'], permissions: [] };
    expect(canAccessPath(menuOnlyUser, productionPath)).toBe(false);
    expect(canAccessPath({ ...menuOnlyUser, action_permission_codes: ['config.view', 'config.system.manage'] }, productionPath)).toBe(true);
  });

  it('父菜单跟随可见子菜单显示，不要求先额外授予父菜单码', () => {
    const childPath = '/development/requirements';
    const childMenu = menuPermissionRegistry.find((item) => item.metadata.path === childPath);
    const filtered = filterMenuItems({ user_type: 'internal', menu_permission_codes: [childMenu.code], action_permission_codes: ['development.requirement.view'], permissions: [] });
    const development = filtered.find((item) => item.label === '产品开发');
    expect(development?.children.some((item) => item.path === childPath)).toBe(true);
  });

  it('权限页面按树承载快速档位和高级权限', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('buildPermissionTree');
    expect(page).toContain('package_selections');
    expect(page).toContain('extra_permission_codes');
    expect(page).toContain(':value="permission.code"');
  });
});
