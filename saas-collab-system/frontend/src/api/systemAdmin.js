import { requestWithMockFallback } from './request';
import {
  mockDepartments,
  mockPermissions,
  mockRoleScopeOptions,
  mockRoles,
  mockSecurityOperations,
  mockTenants,
  mockUsers
} from '../mock/systemAdmin';

export const fetchTenants = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/tenants/', params }, mockTenants, 'system.tenants'
);

export const fetchDepartments = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/departments/', params }, mockDepartments, 'system.departments'
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

export const fetchUsers = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/users/', params }, mockUsers, 'system.users'
);
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
  mockWrite({ id, ...payload }), 'system.users.update'
);
export const resetUserPassword = (id, payload) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/system/users/${id}/reset-password/`, data: payload },
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
