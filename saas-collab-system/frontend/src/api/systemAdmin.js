import { explicitMockMode, requestApi, requestWithMockFallback } from './request';
import {
  mockDepartments,
  mockDepartmentTree,
  mockPermissions,
  mockRoleScopeOptions,
  mockRoles,
  mockSecurityOperations,
  mockTenants,
  mockUsers,
  mockUpdateUserProfile
} from '../mock/systemAdmin';

export const fetchTenants = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/tenants/', params }, mockTenants, 'system.tenants'
);

export const fetchDepartments = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/departments/', params }, mockDepartments, 'system.departments'
);
export const fetchDepartmentTree = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/departments/tree/', params },
  mockDepartmentTree,
  'system.department_tree'
);
const mockWrite = (data) => () => ({ success: true, code: 'OK', message: 'Mock操作已记录', data: { ...data, api_status: 'mock' } });

export const createDepartment = (payload) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/system/departments/', data: payload }, mockWrite(payload), 'system.departments.create'
);
export const updateDepartment = (id, payload) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/system/departments/${id}/`, data: payload },
  mockWrite({ id, ...payload }), 'system.departments.update'
);
export const deleteDepartment = (id) => requestWithMockFallback(
  { method: 'delete', url: `/api/internal/system/departments/${id}/` },
  mockWrite({ id, deleted: true }), 'system.departments.delete'
);

// Identity directories must never substitute rehearsal accounts when the
// production API times out or disconnects. Explicit VITE_USE_MOCK=true builds
// still use fixtures, while production-like builds fail closed with the real
// network error so operators cannot mistake demo identities for tenant users.
export const fetchUsers = (params = {}) => explicitMockMode
  ? requestWithMockFallback(
    { method: 'get', url: '/api/internal/system/users/', params }, mockUsers, 'system.users'
  )
  : requestApi({ method: 'get', url: '/api/internal/system/users/', params });
export const createUser = (payload) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/system/users/', data: payload }, mockWrite(payload), 'system.users.create'
);
export const updateUserStatus = (id, isActive) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/system/users/${id}/status/`, data: { is_active: isActive } },
  mockWrite({ id, is_active: isActive }), 'system.users.status'
);
export const updateUserRoles = (id, roleCodes) => requestWithMockFallback(
  { method: 'put', url: `/api/internal/system/users/${id}/roles/`, data: { role_codes: roleCodes } },
  mockWrite({ id, roles: roleCodes }), 'system.users.roles'
);
export const updateUserProfile = (id, payload) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/system/users/${id}/`, data: payload },
  () => mockUpdateUserProfile(id, payload), 'system.users.update'
);
export const deleteUser = (id) => requestWithMockFallback(
  { method: 'delete', url: `/api/internal/system/users/${id}/` },
  mockWrite({ id, deleted: true }), 'system.users.delete'
);
export const updateUserDepartments = (id, department_id, department_ids) => updateUserProfile(id, {
  department_id,
  department_ids,
});
export const resetUserPassword = (id, payload) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/system/users/${id}/password-reset/`, data: payload },
  mockWrite({ id }), 'system.users.reset_password'
);
export const fetchAssignableRoles = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/user-role-options/', params }, mockRoles, 'system.user_role_options'
);

export const fetchRoles = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/roles/', params }, mockRoles, 'system.roles'
);
export const createRole = (payload, tenantId) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/system/roles/', params: tenantId ? { tenant_id: tenantId } : undefined, data: payload },
  mockWrite(payload), 'system.roles.create'
);
export const copyRole = (id, payload, tenantId) => requestWithMockFallback(
  {
    method: 'post',
    url: `/api/internal/system/roles/${id}/copy/`,
    params: tenantId ? { tenant_id: tenantId } : undefined,
    data: payload,
  },
  mockWrite({ id, ...payload, role_type: 'custom', is_protected: false, status: 'active' }),
  'system.roles.copy'
);
export const fetchRoleScopeOptions = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/role-scope-options/', params },
  mockRoleScopeOptions,
  'system.role_scope_options'
);
export const updateRole = (id, payload, tenantId) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/system/roles/${id}/`, params: tenantId ? { tenant_id: tenantId } : undefined, data: payload },
  mockWrite({ id, ...payload }), 'system.roles.update'
);
export const updateRoleStatus = (id, status, tenantId) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/system/roles/${id}/status/`, params: tenantId ? { tenant_id: tenantId } : undefined, data: { status } },
  mockWrite({ id, status }), 'system.roles.status'
);
export const deleteRole = (id, tenantId) => requestWithMockFallback(
  { method: 'delete', url: `/api/internal/system/roles/${id}/`, params: tenantId ? { tenant_id: tenantId } : undefined },
  mockWrite({ id, deleted: true }), 'system.roles.delete'
);
export const updateRolePermissions = (id, payload, tenantId) => requestWithMockFallback(
  { method: 'put', url: `/api/internal/system/roles/${id}/permissions/`, params: tenantId ? { tenant_id: tenantId } : undefined, data: payload },
  mockWrite({ id, ...payload }), 'system.roles.permissions'
);

export const fetchPermissions = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/permissions/', params }, mockPermissions, 'system.permissions'
);

export const buildMockPermissionPackages = () => {
    const grouped = new Map();
    for (const permission of mockPermissions().data?.results || []) {
      if (!grouped.has(permission.module)) grouped.set(permission.module, []);
      grouped.get(permission.module).push(permission);
    }
    const highRiskParts = new Set([
      'delete', 'review', 'approve', 'export', 'credential', 'authorize', 'revoke', 'rollback',
      'publish', 'production', 'confirm', 'freeze', 'rotate', 'disable', 'verify', 'cancel',
      'clear', 'run_live_readonly', 'execute', 'start', 'resume', 'record', 'deploy', 'restore'
    ]);
    const highRiskPermissionCodes = new Set([
      'system.roles.manage', 'system.users.manage', 'system.organization.manage', 'config.system.manage'
    ]);
    const packages = [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([module, definitions]) => {
      const menus = definitions.filter((item) => item.permission_type === 'menu').map((item) => item.code);
      const fields = definitions.filter((item) => item.permission_type === 'field').map((item) => item.code);
      const actions = definitions.filter((item) => (item.permission_type || 'action') === 'action');
      const highRisk = actions.filter((item) => (
        highRiskPermissionCodes.has(item.code)
        || String(item.action || '').split('.').some((part) => highRiskParts.has(part))
      )).map((item) => item.code);
      const routineDefinitions = actions.filter((item) => !highRisk.includes(item.code));
      const routine = routineDefinitions.map((item) => item.code);
      const read = actions.filter((item) => String(item.action || '').split('.').at(-1) === 'view').map((item) => item.code);
      const readCodes = [...new Set([...menus, ...fields, ...read])].sort();
      const operateActions = routineDefinitions
        .filter((item) => String(item.action || '').split('.').at(-1) !== 'manage')
        .map((item) => item.code);
      const operateCodes = [...new Set([...readCodes, ...operateActions])].sort();
      const adminCodes = [...new Set([...readCodes, ...routine])].sort();
      return { module, levels: { none: [], read: readCodes, operate: operateCodes, admin: adminCodes }, high_risk_codes: highRisk.sort(), available_codes: definitions.map((item) => item.code).sort() };
    });
    return {
    success: true,
    code: 'MOCK',
    message: 'Mock权限包目录',
    data: {
      status: 'mock',
      levels: [
        { code: 'none', name: '无权限' },
        { code: 'read', name: '只读' },
        { code: 'operate', name: '可操作' },
        { code: 'admin', name: '模块管理员' },
      ],
      packages,
      high_risk_policy: 'operate/admin 不自动授予高风险权限，需单独确认。',
    },
    };
};

export const fetchPermissionPackages = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/permission-packages/', params },
  buildMockPermissionPackages,
  'system.permission_packages'
);

// The permission directory is intentionally paginated by the backend. Keep
// the loop here reusable so management pages cannot accidentally render only
// the first page when the catalog grows beyond 100 entries.
export async function fetchAllPermissions(loader = fetchPermissions) {
  const rows = [];
  let page = 1;
  let response = null;
  while (page <= 1000) {
    response = await loader({ page, page_size: 100 });
    if (!response?.success) return { response, rows };
    rows.push(...(response.data?.results || response.data?.items || []));
    const count = Number(response.data?.count);
    if (!response.data?.next || (Number.isFinite(count) && rows.length >= count)) break;
    page += 1;
  }
  return { response, rows };
}

export const fetchSecurityOperations = () => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/security-operations/' }, mockSecurityOperations, 'system.security_operations'
);
