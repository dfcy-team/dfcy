export const apiAccessAdminRoles = new Set(['administrator', 'admin', 'tech_admin', 'integration_admin']);
export function isApiAccessAdmin(user) {
  return Boolean(user?.user_type === 'internal' && user?.is_active !== false && user?.tenant_id
    && (user.is_superuser || (user.roles || []).some(role => apiAccessAdminRoles.has(role))));
}
export const isApiAccessPermission = code => /^(integrations|feishu)\./.test(String(code || ''));
