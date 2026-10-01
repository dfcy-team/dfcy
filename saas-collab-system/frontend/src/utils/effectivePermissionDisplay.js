import { adminDimensionLabel, adminModuleLabel, adminPermissionLabel, adminPermissionSourceLabel, adminPermissionTypeLabel, adminRoleDisplayName } from './adminDisplayLabels';
import { permissionAssignmentAvailability } from './permissionEditor';
import { buildRegisteredMenuTree } from './permissionTree';

export function effectivePermissionModule(permission = {}) {
  if (permission.module) return String(permission.module).toLowerCase();
  const code = String(permission.code || '');
  if (code.startsWith('menu.')) return code.split('.')[1] || 'other';
  if (code.startsWith('field.')) {
    const parts=code.split('.');
    if (parts[1] === 'employee_readonly') return ({ products: 'products', product_details: 'products', stores: 'masterdata', warehouses: 'masterdata' })[parts[2]] || 'system';
    return parts[1] || 'other';
  }
  const match = code.match(/^([a-z][a-z0-9_]*)\./i);
  const module = match?.[1] || 'other';
  return ['employee_readonly', 'employee', 'user'].includes(module) ? 'system' : module;
}

export function effectivePermissionModuleLabel(permission) {
  return adminModuleLabel(effectivePermissionModule(permission));
}

export function isInactiveEffectivePermission(permission = {}) {
  return permission.module_disabled === true || permission.is_active === false || ['inactive', 'retired'].includes(String(permission.status || '').toLowerCase());
}
export function annotateEffectivePermissionAvailability(permissions = [], statuses = {}) {
  const records = permissions.map(permission => ({ ...permission, module: effectivePermissionModule(permission) }));
  const unavailable = permissionAssignmentAvailability(records, buildRegisteredMenuTree(), statuses);
  return records.map(permission => ({ ...permission, module_disabled: unavailable.has(permission.code) }));
}

export function effectivePermissionSourceLabels(permission, roles = []) {
  const roleByKey = new Map();
  roles.forEach(role => { if (role?.id != null) roleByKey.set(String(role.id), role); if (role?.code) roleByKey.set(String(role.code), role); });
  const labels = (permission.sources || []).map(source => {
    const role = roleByKey.get(String(source.role_code || '')) || roleByKey.get(String(source.role_id ?? ''));
    return role ? adminRoleDisplayName(role) : (source.role_code ? adminRoleDisplayName({ code: source.role_code, id: source.role_id }) : adminPermissionSourceLabel(source.source || source.origin));
  });
  return [...new Set(labels)];
}

export function filterEffectivePermissions(permissions = [], options = {}) {
  const { query = '', module = 'all', type = 'all', result = 'all', showInactive = false, roles = [] } = options;
  const needle = String(query).trim().toLocaleLowerCase();
  return permissions.filter(permission => {
    if (!showInactive && isInactiveEffectivePermission(permission)) return false;
    if (module !== 'all' && effectivePermissionModule(permission) !== module) return false;
    if (type !== 'all' && permission.permission_type !== type) return false;
    if (result === 'allowed' && permission.allowed !== true) return false;
    if (result === 'denied' && permission.allowed !== false) return false;
    if (!needle) return true;
    const sources = effectivePermissionSourceLabels(permission, roles).join(' ');
    return `${adminPermissionLabel(permission.code)} ${permission.code || ''} ${sources}`.toLocaleLowerCase().includes(needle);
  });
}

export function paginateEffectivePermissions(permissions = [], page = 1, pageSize = 20) {
  const size = Math.max(1, Number(pageSize) || 20);
  const pages = Math.max(1, Math.ceil(permissions.length / size));
  const current = Math.min(Math.max(1, Number(page) || 1), pages);
  return { items: permissions.slice((current - 1) * size, current * size), page: current, pageSize: size, total: permissions.length, pages };
}
function effectiveScopeLabel(scope, type) {
  if (Array.isArray(scope)) return scope.length ? scope.map(item => effectiveScopeLabel(item, type)).join('；') : (type === 'action' ? '未返回数据范围' : '随对应功能权限');
  if (scope == null) return '未返回数据范围';
  if (scope === 'all' || scope.scope_type === 'all') return '全部数据';
  if (typeof scope === 'string') return ({custom:'业务范围',department:'所属部门',department_tree:'部门及下级',self:'本人数据'})[scope] || '历史范围';
  return Object.entries(scope.config || {}).map(([key, value]) => `${adminDimensionLabel(key)}：${Array.isArray(value) ? value.join('、') : value}`).join('；') || '自定义范围';
}

export function formatEffectivePermissionDetail(permission = {}, roles = []) {
  const roleByKey = new Map();
  roles.forEach(role => { if (role?.id != null) roleByKey.set(String(role.id), role); if (role?.code) roleByKey.set(String(role.code), role); });
  return (permission.sources || []).map(source => {
    const role = roleByKey.get(String(source.role_code || '')) || roleByKey.get(String(source.role_id ?? ''));
    const scope = effectiveScopeLabel(source.scope, permission.permission_type);
    return { source: adminPermissionSourceLabel(source.source || source.origin), role: role ? adminRoleDisplayName(role) : (source.role_code ? adminRoleDisplayName({ code: source.role_code, id: source.role_id }) : '直接授权'), scope, validUntil: source.valid_until || '长期有效', assignedBy: source.assigned_by_id || '—', membershipId: source.membership_id || '—' };
  });
}

export function effectivePermissionTypeLabel(value) { return adminPermissionTypeLabel(value); }
