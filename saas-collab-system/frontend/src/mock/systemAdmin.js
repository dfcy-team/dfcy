import { successResponse } from './index';

const page = (results) => ({ status: 'mock', count: results.length, next: null, previous: null, results });

export const mockTenants = () => successResponse(page([
  { id: 1, name: '演示租户', code: 'demo', status: 'active', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 2, name: '沙箱租户', code: 'sandbox', status: 'active', created_at: '2026-01-02T00:00:00Z', updated_at: '2026-01-02T00:00:00Z' }
]));

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
    permission_codes: ['analytics.view', 'products.status.view'],
    menu_permission_codes: [], action_permission_codes: ['analytics.view', 'products.status.view'], field_permission_codes: [],
    data_scopes: [{ scope_type: 'department', config: {} }]
  },
  {
    id: 2, tenant_id: 1, name: '管理员', code: 'administrator', status: 'active',
    permission_codes: [
      'system.users.view', 'system.roles.view',
      'masterdata.view', 'masterdata.manage',
      'integrations.view', 'integrations.manage', 'integrations.run_live_readonly',
      'integrations.config.view', 'integrations.config.create', 'integrations.config.update',
      'integrations.config.verify', 'integrations.config.disable', 'integrations.credential.rotate',
      'integrations.store.view', 'integrations.store.authorize', 'integrations.store.revoke',
      'integrations.warehouse.view', 'integrations.warehouse.authorize', 'integrations.warehouse.revoke'
    ],
    menu_permission_codes: [
      'menu.system.organization.view', 'menu.system.users.view', 'menu.system.roles.view',
      'menu.system.security_operations.view'
    ],
    action_permission_codes: [
      'system.users.view', 'system.roles.view', 'masterdata.view', 'masterdata.manage',
      'integrations.view', 'integrations.manage', 'integrations.run_live_readonly',
      'integrations.config.view', 'integrations.config.create', 'integrations.config.update',
      'integrations.config.verify', 'integrations.config.disable', 'integrations.credential.rotate',
      'integrations.store.view', 'integrations.store.authorize', 'integrations.store.revoke',
      'integrations.warehouse.view', 'integrations.warehouse.authorize', 'integrations.warehouse.revoke'
    ],
    field_permission_codes: [
      'field.system.users.full_name.view', 'field.system.users.department.view',
      'field.system.users.roles.view', 'field.system.users.status.view'
    ],
    data_scopes: [{ scope_type: 'all', config: {} }]
  }
]));

export const mockRoleScopeOptions = () => successResponse({
  status: 'mock',
  api_status: 'mock',
  departments: [
    { id: 1, tenant_id: 1, name: '经营中心', parent_id: null, parent_name: '', status: 'active' },
    { id: 2, tenant_id: 1, name: '供应链组', parent_id: 1, parent_name: '经营中心', status: 'active' }
  ],
  users: [
    { id: 1, username: 'demo-operator', full_name: '演示运营', user_type: 'internal', is_active: true },
    { id: 2, username: 'demo-finance', full_name: '演示财务', user_type: 'internal', is_active: false }
  ],
  roles: [
    { id: 1, name: '运营只读', code: 'operator_viewer', status: 'active' },
    { id: 2, name: '管理员', code: 'administrator', status: 'active' }
  ]
});

export const mockPermissions = () => successResponse(page([
  { id: 1, code: 'menu.system.users.view', name: '查看用户目录菜单', module: 'system', action: 'users.view', permission_type: 'menu', metadata: { path: '/system/users', resource: 'users' }, description: '显示用户目录入口' },
  { id: 2, code: 'menu.system.roles.view', name: '查看角色权限菜单', module: 'system', action: 'roles.view', permission_type: 'menu', metadata: { path: '/system/roles', resource: 'roles' }, description: '显示角色权限入口' },
  { id: 3, code: 'system.users.view', name: '查看用户目录', module: 'system', action: 'users.view', permission_type: 'action', metadata: {}, description: '租户内用户只读访问' },
  { id: 4, code: 'system.users.manage', name: '管理用户目录', module: 'system', action: 'users.manage', permission_type: 'action', metadata: {}, description: '租户内用户启停和角色绑定' },
  { id: 5, code: 'masterdata.view', name: '查看基础档案与连接器识别', module: 'masterdata', action: 'view', permission_type: 'action', metadata: {}, description: '查看当前租户的平台、站点、店铺、仓库和供应商基础档案，以及仓储业务分类、服务商名称和连接器识别结果；不包含实际连接器配置或凭据内容。' },
  { id: 6, code: 'masterdata.manage', name: '维护基础档案与服务商标识', module: 'masterdata', action: 'manage', permission_type: 'action', metadata: {}, description: '创建、更新、启停当前租户的平台、站点、店铺、仓库和供应商基础档案，并维护仓储业务分类与服务商识别信息；不授予实际连接器配置或凭据轮换操作。' },
  { id: 7, code: 'field.system.users.full_name.view', name: '查看用户姓名字段', module: 'system', action: 'users.full_name.view', permission_type: 'field', metadata: { resource: 'users', field: 'full_name', operation: 'view' }, description: '显示姓名字段' },
  { id: 8, code: 'field.system.users.status.view', name: '查看用户状态字段', module: 'system', action: 'users.status.view', permission_type: 'field', metadata: { resource: 'users', field: 'is_active', operation: 'view' }, description: '显示启用状态字段' },
  { id: 9, code: 'integrations.config.view', name: '查看 API/WMS 连接配置', module: 'integrations', action: 'config.view', permission_type: 'action', metadata: {}, description: '查看当前租户的实际连接器配置元数据和脱敏状态；不读取或导出凭据，也不代表拥有创建、更新、验证或停用权限。' },
  { id: 10, code: 'integrations.config.create', name: '创建 API/WMS 连接配置', module: 'integrations', action: 'config.create', permission_type: 'action', metadata: {}, description: '为当前租户创建实际连接器配置草稿并登记服务商连接信息；不授予更新、验证、停用或凭据轮换权限。' },
  { id: 11, code: 'integrations.config.update', name: '更新 API/WMS 连接配置', module: 'integrations', action: 'config.update', permission_type: 'action', metadata: {}, description: '更新当前租户已授权的实际连接器非敏感配置；不改变仓储业务分类，不读取凭据，也不授予验证、停用或凭据轮换权限。' },
  { id: 12, code: 'integrations.config.verify', name: '验证 API/WMS 连接配置', module: 'integrations', action: 'config.verify', permission_type: 'action', metadata: {}, description: '对当前租户的实际连接器配置执行受控连接验证并记录结果；不授予修改配置、停用连接或轮换凭据权限。' },
  { id: 13, code: 'integrations.config.disable', name: '停用 API/WMS 连接配置', module: 'integrations', action: 'config.disable', permission_type: 'action', metadata: {}, description: '停用当前租户的实际连接器配置并阻止后续接入任务使用；不删除平台档案、不清理凭据，也不授予凭据轮换权限。' },
  { id: 14, code: 'integrations.credential.rotate', name: '轮换 API/WMS 凭据', module: 'integrations', action: 'credential.rotate', permission_type: 'action', metadata: {}, description: '只轮换 API/WMS 连接器的受控凭据引用或密钥版本，不读取、导出原始凭据；不授予连接配置创建、更新、验证或停用权限。' },
  { id: 15, code: 'integrations.view', name: '查看集成配置', module: 'integrations', action: 'view', permission_type: 'action', metadata: {}, description: '查看集成配置及 API 接入入口；不读取或导出原始凭据。' },
  { id: 16, code: 'integrations.manage', name: '管理集成配置', module: 'integrations', action: 'manage', permission_type: 'action', metadata: {}, description: '管理已授权的集成配置和同步任务；不授予生产写入能力。' },
  { id: 17, code: 'integrations.run_live_readonly', name: '运行生产只读同步', module: 'integrations', action: 'run_live_readonly', permission_type: 'action', metadata: {}, description: '按审批和数据范围执行一次生产平台只读检查；不会写入平台。' },
  { id: 18, code: 'integrations.store.view', name: '查看平台店铺授权', module: 'integrations', action: 'store.view', permission_type: 'action', metadata: {}, description: '查看当前租户店铺 API 授权的脱敏关系；不读取或导出凭据。' },
  { id: 19, code: 'integrations.store.authorize', name: '授权平台店铺', module: 'integrations', action: 'store.authorize', permission_type: 'action', metadata: {}, description: '发起受控店铺 OAuth 授权；不回显原始令牌。' },
  { id: 20, code: 'integrations.store.revoke', name: '撤销平台店铺授权', module: 'integrations', action: 'store.revoke', permission_type: 'action', metadata: {}, description: '撤销店铺 API 授权并记录审计；不删除连接配置。' },
  { id: 21, code: 'integrations.warehouse.view', name: '查看仓库 API 授权', module: 'integrations', action: 'warehouse.view', permission_type: 'action', metadata: {}, description: '查看当前租户仓库与库存 API 接入配置的脱敏授权关系；不读取或导出凭据。' },
  { id: 22, code: 'integrations.warehouse.authorize', name: '绑定仓库 API 配置', module: 'integrations', action: 'warehouse.authorize', permission_type: 'action', metadata: {}, description: '将当前租户已托管且通过校验的库存 API 配置绑定到仓库；不接收或回显原始凭据。' },
  { id: 23, code: 'integrations.warehouse.revoke', name: '解除仓库 API 绑定', module: 'integrations', action: 'warehouse.revoke', permission_type: 'action', metadata: {}, description: '撤销当前租户仓库的库存 API 授权绑定并记录审计；不删除接入配置或凭据。' }
]));

export const mockSecurityOperations = () => successResponse({
  status: 'mock',
  summary: { active_users: 12, inactive_users: 2, active_roles: 6, credential_references: 1 },
  accounts: [
    { id: 1, username: 'demo-operator', full_name: '演示运营', user_type: 'internal', is_active: true },
    { id: 2, username: 'demo-disabled', full_name: '演示停用账号', user_type: 'internal', is_active: false }
  ],
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
