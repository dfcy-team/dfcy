import { requestWithMockFallback } from './request';
import {
  mockDepartments,
  mockPermissions,
  mockRoles,
  mockSecurityOperations,
  mockUsers
} from '../mock/systemAdmin';

export const fetchDepartments = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/departments/', params }, mockDepartments, 'system.departments'
);
const mockWrite = (data) => () => ({ success: true, code: 'OK', message: 'Mock操作已记录', data: { ...data, api_status: 'mock' } });

export const createDepartment = (payload) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/system/departments/', data: payload }, mockWrite(payload), 'system.departments.create'
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
export const fetchAssignableRoles = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/user-role-options/', params }, mockRoles, 'system.user_role_options'
);

export const fetchRoles = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/roles/', params }, mockRoles, 'system.roles'
);
export const createRole = (payload) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/system/roles/', data: payload }, mockWrite(payload), 'system.roles.create'
);
export const updateRolePermissions = (id, payload) => requestWithMockFallback(
  { method: 'put', url: `/api/internal/system/roles/${id}/permissions/`, data: payload },
  mockWrite({ id, ...payload }), 'system.roles.permissions'
);

export const fetchPermissions = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/permissions/', params }, mockPermissions, 'system.permissions'
);
export const fetchSecurityOperations = () => requestWithMockFallback(
  { method: 'get', url: '/api/internal/system/security-operations/' }, mockSecurityOperations, 'system.security_operations'
);
