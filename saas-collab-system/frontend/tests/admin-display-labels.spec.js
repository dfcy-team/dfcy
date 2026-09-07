import { describe, expect, it } from 'vitest';
import { adminModuleLabel, adminPermissionLabel, adminRoleDisplayName, departmentDisplayName } from '../src/utils/adminDisplayLabels';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const hasLatin = (value) => /[A-Za-z]/u.test(String(value || ''));

describe('系统管理中文显示', () => {
  it('覆盖权限目录模块，未知模块统一显示为其他模块', () => {
    for (const module of ['alerts', 'analytics', 'audit', 'config', 'development', 'finance', 'governance', 'influencers', 'integrations', 'listings', 'masterdata', 'pilot', 'products', 'purchasing', 'replenishment', 'reports', 'rpa', 'sales_management', 'security', 'suppliers', 'system', 'workflow']) {
      expect(adminModuleLabel(module), module).not.toBe('其他模块');
      expect(hasLatin(adminModuleLabel(module)), module).toBe(false);
    }
    expect(adminModuleLabel('new_module')).toBe('其他模块');
  });

  it('权限名称遇到英文旧数据时仍生成全中文标签', () => {
    for (const permission of [
      { code: 'integrations.config.view', name: '查看 API/WMS 连接配置' },
      { code: 'rpa.tasks.view', name: 'View RPA tasks' },
      { code: 'governance.api.view', name: 'View API contracts' },
      { code: 'unknown.new_action.view', name: 'View unknown permission' },
    ]) expect(hasLatin(adminPermissionLabel(permission)), permission.code).toBe(false);
  });

  it('部门名称按用户输入的保存值原样显示', () => {
    expect(departmentDisplayName('SHOPEE运营部')).toBe('SHOPEE运营部');
    expect(departmentDisplayName('TIKTOK运营部')).toBe('TIKTOK运营部');
    expect(departmentDisplayName('短视频运营部')).toBe('短视频运营部');
    const page = read('src/views/system/DepartmentDirectory.vue');
    expect(page).toContain('departmentDisplayName(value)');
    expect(page).toContain('departmentDisplayName(item.name)');
    expect(page).toContain('resourcePage.value?.openEdit(node)');
  });

  it('内置角色和遗留测试角色使用简短中文名称', () => {
    expect(adminRoleDisplayName({ code: 'operations', name: 'Operations' })).toBe('业务运营人员');
    expect(adminRoleDisplayName({ id: 8, code: 'pilot-admin-x', name: 'Pilot E2E admin' })).toBe('试点管理员');
    expect(adminRoleDisplayName({ id: 9, code: 'bd', name: 'BD' })).toBe('商务拓展');
    expect(adminRoleDisplayName({ id: 10, code: 'custom-x', name: 'Unknown Role' })).toBe('自定义角色10');
  });

  it('权限页面不在普通界面显示编码、英文分层或权限说明', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('placeholder="搜索角色名称"');
    expect(page).not.toContain('角色编码');
    expect(page).not.toContain('permission.description ||');
    expect(page).not.toContain('class="permission-code"');
    expect(page).toContain('module.label');
    expect(page).toContain('adminPermissionLabel(permission)');
  });
});
