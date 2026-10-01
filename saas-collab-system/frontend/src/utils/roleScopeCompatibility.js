const PLATFORM_DETAIL_PERMISSION_CODES = new Set([
  'menu.listings.products_platform_details.view',
  'listings.product_detail.view',
  'listings.product_detail.manage',
  'listings.product_detail.import',
]);

const INCOMPATIBLE_PLATFORM_DETAIL_SCOPE_KEYS = ['warehouse_ids', 'supplier_ids'];

export function hasPlatformDetailScopeConflict(permissionCodes = [], scopeConfig = {}) {
  const grantsPlatformDetails = permissionCodes.some((code) => PLATFORM_DETAIL_PERMISSION_CODES.has(code));
  const hasIncompatibleScope = INCOMPATIBLE_PLATFORM_DETAIL_SCOPE_KEYS.some((key) => scopeConfig?.[key]?.length);
  return grantsPlatformDetails && hasIncompatibleScope;
}
