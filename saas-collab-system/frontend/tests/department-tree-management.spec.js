import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('步骤7 共享组织树与用户目录契约', () => {
  it('共享 DepartmentTree 提供搜索、选择、未分配节点及受权限保护的管理动作', () => {
    const tree = read('src/components/DepartmentTree.vue');
    for (const phrase of [
      '<el-tree', 'default-expand-all', 'filter-node-method', 'filterTree',
      "select-all", "showAll", "select-unassigned", "add-child", "toggle-status", "canManage"
    ]) {
      expect(tree).toContain(phrase);
    }
  });

  it('组织架构页和用户目录共用树接口与组件', () => {
    const departmentPage = read('src/views/system/DepartmentDirectory.vue');
    const userPage = read('src/views/system/UserDirectory.vue');
    for (const page of [departmentPage, userPage]) {
      expect(page).toContain("from '../../components/DepartmentTree.vue'");
      expect(page).toContain('fetchDepartmentTree');
    }
    expect(departmentPage).toContain('system.organization.manage');
    expect(departmentPage).toContain('@add-child="addChildDepartment"');
    expect(departmentPage).toContain('@toggle-status="toggleDepartment"');
    expect(departmentPage).toContain('@delete="deleteDepartment"');
    expect(departmentPage).not.toContain('draggable');
  });

  it('用户目录传递部门、下级和未分配筛选，并提供部门调整入口', () => {
    const userPage = read('src/views/system/UserDirectory.vue');
    for (const phrase of [
      'department_id', 'include_descendants', 'unassigned', '仅直属', '包含下级',
      '未分配人员', '全部可见用户', 'updateUserDepartments', 'system.users.manage',
      'field.system.users.department.view', '主部门', '兼任部门'
    ]) {
      expect(userPage).toContain(phrase);
    }
    expect(userPage).toContain(':external-filters="departmentFilters"');
    expect(userPage).toContain('system.organization.view');
    expect(userPage).toContain('departmentTreeVisible');
    expect(userPage).toContain('selectAllUsers');
    expect(userPage).toContain('departmentAccess.visible && departmentFieldVisible');
  });

  it('接口和 mock 对齐树、用户筛选及部门更新形状', () => {
    const api = read('src/api/systemAdmin.js');
    const mock = read('src/mock/systemAdmin.js');
    expect(api).toContain('/api/internal/system/departments/tree/');
    expect(api).toContain('updateUserDepartments');
    expect(mock).toContain('mockDepartmentTree');
    expect(mock).toContain('params.unassigned');
    expect(mock).toContain('params.include_descendants');
    expect(mock).toContain('department_ids');
  });

  it('角色权限矩阵公开历史组织范围兼容提示和新的业务范围配置', () => {
    const rolePage = read('src/views/system/RolePermissionMatrix.vue');
    expect(rolePage).not.toContain('value="department_tree"');
    expect(rolePage).toContain('历史组织范围，需重新配置');
    expect(rolePage).toContain('platform_ids');
    expect(rolePage).toContain('supplier_ids');
  });
});
