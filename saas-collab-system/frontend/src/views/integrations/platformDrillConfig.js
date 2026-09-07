const WAREHOUSE_PLATFORMS = new Set(['jifeng_wms']);

/**
 * The collection endpoint serializes api_type under platform_config while
 * older/mock payloads may expose it at the top level. Keep the drill page
 * independent from either response shape.
 */
export function platformDrillApiType(config = {}) {
  const configured = config?.api_type || config?.platform_config?.api_type;
  if (configured) return String(configured).trim().toLowerCase();

  if (String(config?.subject_type || '').trim().toLowerCase() === 'warehouse') return 'inventory';

  const platform = String(config?.platform || '').trim().toLowerCase();
  return WAREHOUSE_PLATFORMS.has(platform) ? 'inventory' : 'marketplace';
}

export function normalizePlatformDrillConfig(config, detail = null) {
  if (!config) return null;
  const merged = detail ? { ...config, ...detail } : { ...config };
  return { ...merged, api_type: platformDrillApiType(merged) };
}

export function isWarehousePlatformDrillConfig(config) {
  return platformDrillApiType(config) === 'inventory';
}
