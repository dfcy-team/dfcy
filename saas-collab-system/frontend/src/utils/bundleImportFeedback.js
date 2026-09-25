const FIELD_LABELS = {
  product_name: '组合商品名称',
  category_node: '末级分类',
  season_code: '属性编码',
  color_code: '组合颜色英文编码',
  legacy_spu_code: '旧SPU编码',
  legacy_sku_code: '旧SKU编码',
  components: '组成SKU',
  component_sku: '单品SKU',
  quantity: '数量',
  cost_allocation_ratio: '成本价分摊比',
  sku_code: '生成的SKU编码',
  non_field_errors: '整行',
  detail: '详情',
};

function fieldErrors(value, path = '') {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => fieldErrors(item, typeof item === 'object' && item !== null ? `${path}${path ? ' ' : ''}第${index + 1}项` : path));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) => fieldErrors(item, [path, FIELD_LABELS[key] || key].filter(Boolean).join(' / ')));
  }
  const message = String(value ?? '').trim();
  return message ? [`${path ? `${path}：` : ''}${message}`] : [];
}

export function bundleImportErrorMessage(error) {
  const payload = error?.response?.data || error;
  const details = fieldErrors(payload?.data);
  if (details.length) return details.join('；');
  const message = payload?.message || error?.message;
  return message || '导入失败，服务端未返回具体原因';
}

export function bundleImportErrorCsvRows(summary) {
  const toRow = (kind, item) => [
    item.line, kind, item.legacySpuCode || '', item.legacySkuCode || '', item.name || '', item.message,
  ];
  return [
    ...(summary.errors || []).map((item) => toRow('商品导入', item)),
    ...(summary.imageErrors || []).map((item) => toRow('图片缓存', item)),
  ];
}
