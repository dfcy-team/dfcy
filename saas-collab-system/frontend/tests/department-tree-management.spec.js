import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import ElementPlus from 'element-plus';
import { flushPromises, mount } from '@vue/test-utils';
import DepartmentDirectory from '../src/views/system/DepartmentDirectory.vue';
import * as systemAdminApi from '../src/api/systemAdmin';

const apiMocks = vi.hoisted(() => ({
  fetchDepartmentTree: vi.fn(), fetchDepartments: vi.fn(), fetchDepartmentLeaderOptions: vi.fn(),
  updateDepartment: vi.fn(), createDepartment: vi.fn(), deleteDepartment: vi.fn(),
}));
vi.mock('../src/api/systemAdmin', () => apiMocks);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const ok = data => ({ success: true, data });
const node = { id: 12, name: '财务部', parent_id: null, status: 'active', leader_id: 41, leader_name: '林主管', leader_include_descendants: true, children: [] };
const DepartmentTreeHarness = defineComponent({
  props: ['nodes'],
  emits: ['edit'],
  setup(props, { emit }) {
    return () => h('button', { onClick: () => emit('edit', props.nodes[0]) }, '编辑树节点');
  },
});

beforeEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
  apiMocks.fetchDepartmentTree.mockResolvedValue(ok({ items: [node] }));
  apiMocks.fetchDepartments.mockResolvedValue(ok({ results: [], count: 0 }));
  apiMocks.fetchDepartmentLeaderOptions.mockResolvedValue(ok({ items: [{ id: 41, username: 'lin', full_name: '林主管' }] }));
  apiMocks.updateDepartment.mockResolvedValue(ok({ id: node.id }));
});

async function mountDepartmentPage() {
  vi.useFakeTimers();
  const wrapper = mount(DepartmentDirectory, {
    attachTo: document.body,
    global: { plugins: [ElementPlus], stubs: {
      AppPage: { template: '<main><slot name="action"/><slot/></main>' },
      AppState: true, DepartmentTree: DepartmentTreeHarness, ElSelect: true, ElPagination: true, teleport: true,
    } },
  });
  await flushPromises();
  await vi.advanceTimersByTimeAsync(300);
  await flushPromises();
  vi.useRealTimers();
  return wrapper;
}

describe('步骤7 共享组织树与用户目录契约', () => {
  it('共享 DepartmentTree 提供搜索、选择、未分配节点及受权限保护的管理动作', () => {
    const tree = read('src/components/DepartmentTree.vue');
    for (const phrase of [
      '<el-tree', 'default-expand-all', 'filter-node-method', 'filterTree',
      "select-all", "showAll", "select-unassigned", "add-child", "toggle-status", "canManage",
      '<el-dropdown', 'handleAction', 'departmentDisplayName(data.name)'
    ]) {
      expect(tree).toContain(phrase);
    }
    expect(tree).not.toContain('@click.stop="$emit(\'add-child\', data)"');
    expect(tree).not.toContain('@click.stop="$emit(\'edit\', data)"');
    expect(tree).not.toContain('@click.stop="$emit(\'toggle-status\', data)"');
    expect(tree).not.toContain('@click.stop="$emit(\'delete\', data)"');
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
    expect(api).toContain('/api/internal/system/departments/leader-options/');
  });

  it('真实挂载组织页和 AdminResourcePage：树编辑保留负责人字段并成功 PATCH', async () => {
    const wrapper = await mountDepartmentPage();
    expect(systemAdminApi.fetchDepartmentLeaderOptions).toHaveBeenCalledWith({ search: '' });
    await wrapper.findAll('button').find(button => button.text() === '编辑树节点').trigger('click');
    await flushPromises();
    await wrapper.find('.el-dialog__footer .el-button--primary').trigger('click');
    await flushPromises();
    expect(systemAdminApi.updateDepartment).toHaveBeenCalledWith(12, expect.objectContaining({
      leader_id: 41, leader_include_descendants: true,
    }));
    wrapper.unmount();
    document.body.innerHTML = '';
  });

  it('负责人候选加载失败时在表单中显示可恢复错误状态', async () => {
    apiMocks.fetchDepartmentLeaderOptions.mockRejectedValueOnce(new Error('候选接口不可用'));
    const wrapper = await mountDepartmentPage();
    await wrapper.findAll('button').find(button => button.text() === '编辑树节点').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('负责人候选加载失败，请检查权限或重试。');
    wrapper.unmount();
    document.body.innerHTML = '';
  });

  it('组织架构编辑将根部门的空上级值规范为 null，并显示字段校验原因', () => {
    const page = read('src/views/system/DepartmentDirectory.vue');
    expect(page).toContain('normalizeDepartmentPayload');
    expect(page).toContain('normalized.parent_id = null');
    expect(page).toContain('withDepartmentError');
    expect(page).toContain('上级部门请选择有效部门；根部门请留空。');
  });

  it('角色权限矩阵公开历史组织范围兼容提示和新的业务范围配置', () => {
    const rolePage = read('src/views/system/RolePermissionMatrix.vue');
    expect(rolePage).not.toContain('value="department_tree"');
    expect(rolePage).toContain('历史组织范围，需重新配置');
    expect(rolePage).toContain('platform_ids');
    expect(rolePage).toContain('supplier_ids');
  });
});
