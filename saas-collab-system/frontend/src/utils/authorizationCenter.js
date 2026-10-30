export const authorizationCenterPath = '/integrations/authorization-center';
export const authorizationPermission = kind => kind === 'warehouse' ? 'integrations.warehouse.view' : 'integrations.store.view';
export function authorizationQuery(kind, platform, status, page) {
  const params = { page, page_size: 20 };
  if (status) params.status = status;
  if (platform) params[kind === 'warehouse' ? 'provider' : 'platform'] = platform;
  return params;
}
export function authorizationSummary(row, kind) {
  const warehouse = kind === 'warehouse';
  return {
    id: row.id,
    name: (warehouse ? row.warehouse_name : row.store_name) || '未提供名称',
    code: (warehouse ? row.warehouse_code : row.store_code) || '—',
    platform: (warehouse ? row.provider : row.platform) || '—',
    region: (warehouse ? row.country_code : row.region) || '—',
    externalId: (warehouse ? row.external_warehouse_code : row.platform_store_id) || '—',
    expiresAt: (warehouse ? row.oauth_expires_at : row.expires_at) || '',
    status: row.status || 'unknown',
    configId: row.integration_config_id,
    subjectId: warehouse ? row.warehouse_id : row.store_id,
    // Whitelist business metadata; credentials and contact details never enter this projection.
    lastError: row.last_error_code || '',
    readEnabled: warehouse ? row.read_enabled : undefined
  };
}
