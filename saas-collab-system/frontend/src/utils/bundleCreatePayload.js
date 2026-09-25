export function buildBundleCreatePayload({ spuMode = 'new', existingSpu = null, name, category, season, color, legacySpuCode = '', legacySkuCode = '', components }) {
  return {
    spu_mode: spuMode,
    ...(spuMode === 'existing' ? { existing_spu: existingSpu } : {}),
    product_name: name,
    category_node: category,
    season_code: season,
    legacy_spu_code: legacySpuCode,
    legacy_sku_code: legacySkuCode,
    color_code: color,
    components: components.map((component) => ({
      component_sku: component.sku,
      quantity: component.quantity,
      cost_allocation_ratio: component.costRatio ?? 1,
    })),
  };
}
