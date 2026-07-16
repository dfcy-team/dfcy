import { successResponse } from './index';

const page = (results) => ({ status: 'mock', count: results.length, next: null, previous: null, results });

export const mockDepartments = () => successResponse(page([
  { id: 1, tenant_id: 1, name: '经营中心', parent_id: null, parent_name: '', status: 'active' },
  { id: 2, tenant_id: 1, name: '供应链组', parent_id: 1, parent_name: '经营中心', status: 'active' }
]));

export const mockUsers = () => successResponse(page([
  {
    id: 1, tenant_id: 1, username: 'demo-operator', email_masked: 'd***@example.com', phone_masked: '***1200',
    user_type: 'internal', is_active: true, department_name: '经营中心', roles: ['operator']
  },
  {
    id: 2, tenant_id: 1, username: 'demo-finance', email_masked: 'f***@example.com', phone_masked: '***2600',
    user_type: 'internal', is_active: false, department_name: '财务组', roles: ['finance_viewer']
  }
]));

export const mockRoles = () => successResponse(page([
  {
    id: 1, tenant_id: 1, name: '运营只读', code: 'operator_viewer', status: 'active',
    permission_codes: ['analytics.view', 'products.status.view'], data_scopes: [{ scope_type: 'department', config: {} }]
  },
  {
    id: 2, tenant_id: 1, name: '系统管理员', code: 'system_admin', status: 'active',
    permission_codes: ['system.users.view', 'system.roles.view', 'masterdata.view'], data_scopes: [{ scope_type: 'all', config: {} }]
  }
]));

export const mockPermissions = () => successResponse(page([
  { id: 1, code: 'system.users.view', name: '查看用户目录', module: 'system', action: 'users.view', description: '租户内用户只读访问' },
  { id: 2, code: 'system.users.manage', name: '管理用户目录', module: 'system', action: 'users.manage', description: '租户内用户启停和角色绑定' },
  { id: 3, code: 'masterdata.view', name: '查看基础档案', module: 'masterdata', action: 'view', description: '租户内基础档案只读访问' },
  { id: 4, code: 'masterdata.manage', name: '管理基础档案', module: 'masterdata', action: 'manage', description: '租户内基础档案维护' }
]));

export const mockSecurityOperations = () => successResponse({
  status: 'mock',
  summary: { active_users: 12, inactive_users: 2, active_roles: 6, credential_references: 1 },
  credential_contract: 'alias_fingerprint_reference_only',
  credential_references: [
    {
      id: 1, platform: 'mock', account_alias: 'demo-sandbox-account', environment: 'sandbox', status: 'disabled',
      credential_fingerprint: 'demo-fingerprint-7f21', credential_key_version: 'demo-v1', last_verified_at: null
    }
  ],
  recent_audit: [
    { id: 1, module: 'system', action: 'role_permissions_update', object_type: 'role', object_id: '2', created_at: '2026-07-16T08:00:00Z' }
  ]
});
