import { describe, expect, it } from 'vitest';
import { buildPermissionTree, buildRegisteredMenuTree, detectMenuRegistryDrift, permissionModuleFromCode } from '../src/utils/permissionTree';
import { canAccessPath, filterMenuItems, menuItems, menuPermissionRegistry } from '../src/router/menu';
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

  it('菜单授权可进入对应只读页面，但不能替代写操作权限', () => {
    const rolesPath = '/system/roles';
    const rolesMenu = menuPermissionRegistry.find((item) => item.metadata.path === rolesPath);
    const menuOnlyUser = {
      user_type: 'internal',
      menu_permission_codes: [rolesMenu.code],
      action_permission_codes: [],
      permissions: [],
    };
    expect(canAccessPath(menuOnlyUser, rolesPath)).toBe(true);
    expect(menuOnlyUser.action_permission_codes).not.toContain('system.roles.manage');
  });

  it('父菜单跟随可见子菜单显示，不要求先额外授予父菜单码', () => {
    const childPath = '/development/requirements';
    const childMenu = menuPermissionRegistry.find((item) => item.metadata.path === childPath);
    const filtered = filterMenuItems({ user_type: 'internal', menu_permission_codes: [childMenu.code], action_permission_codes: ['development.requirement.view'], permissions: [] });
    const development = filtered.find((item) => item.label === '产品开发');
    expect(development?.children.some((item) => item.path === childPath)).toBe(true);
  });

  it('每个侧边栏页面都有菜单登记，无操作权限的页面仍按菜单授权', () => {
    const paths = [];
    const collect = (items) => {
      for (const item of items || []) {
        if (item.path && item.path !== '/') paths.push(item.path);
        collect(item.children);
      }
    };
    collect(menuItems);
    const registeredPaths = new Set(menuPermissionRegistry.map((item) => item.metadata.path));
    expect([...new Set(paths)].filter((path) => !registeredPaths.has(path))).toEqual([]);

    const pricingPath = '/pricing/prices';
    const pricingMenu = menuPermissionRegistry.find((item) => item.metadata.path === pricingPath);
    expect(pricingMenu).toMatchObject({ code: 'menu.sales_management.pricing_prices.view' });
    expect(canAccessPath({ user_type: 'internal', menu_permission_codes: [pricingMenu.code], action_permission_codes: [] }, pricingPath)).toBe(true);
    expect(canAccessPath({ user_type: 'internal', menu_permission_codes: [], action_permission_codes: [] }, pricingPath)).toBe(false);
  });

  it('权限页面按树承载快速档位和高级权限', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('buildPermissionTree');
    expect(page).toContain('package_selections');
    expect(page).toContain('extra_permission_codes');
    expect(page).toContain(':value="permission.code"');
  });

  it('新增注册菜单自动进入中文菜单节点，并检测 API 目录漂移', () => {
    const menuItems = [{ label: '系统管理', children: [{
      path: '/system/audit-console', label: '审计台',
      permissions: ['system.audit.view'], menuPermissions: ['menu.system.audit_console.view'],
    }] }];
    const permissions = [
      { code: 'menu.system.audit_console.view', module: 'system', permission_type: 'menu' },
      { code: 'system.audit.view', module: 'system', permission_type: 'action' },
      { code: 'field.system.audit.secret.view', module: 'system', permission_type: 'field' },
    ];
    const tree = buildRegisteredMenuTree({ menuItems });
    const item = tree[0].children.find((node) => node.label === '审计台');
    expect(item).toMatchObject({ code: 'menu.system.audit_console.view', label: '审计台', action_codes: ['system.audit.view'] });
    expect(detectMenuRegistryDrift({ menuItems, permissions: permissions.slice(1) })).toEqual([
      { code: 'menu.system.audit_console.view', name: '审计台', path: '/system/audit-console' },
    ]);
  });

  it('高级权限树保留注册菜单的真实一级归属', () => {
    const menuItems = [
      { label: 'API数据接入', children: [{ path: '/platforms', label: '平台档案', permissions: ['masterdata.view'] }] },
      { label: '基础档案', children: [{ path: '/stores', label: '店铺档案', permissions: ['masterdata.view'] }] },
    ];
    const tree = buildRegisteredMenuTree({ menuItems });
    expect(tree.map((item) => item.label)).toEqual(['API数据接入', '基础档案']);
    expect(tree[0].children[0]).toMatchObject({ label: '平台档案', path: '/platforms' });
    expect(tree[1].children[0]).toMatchObject({ label: '店铺档案', path: '/stores' });
  });
});
