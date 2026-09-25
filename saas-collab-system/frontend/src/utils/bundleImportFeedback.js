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
  existing_spu: '已有组合SPU',
  spu_mode: '组合SPU创建方式',
  non_field_errors: '整行',
  detail: '详情',
};

function readableValidationMessage(message, key) {
  if (key === 'existing_spu' && message === 'This field may not be null.') {
    return '选择已有组合SPU时必须提供编号；新建组合SPU时不应提交此字段';
  }
  if (key === 'existing_spu' && message === 'This field is required when spu_mode is existing.') {
    return '选择已有组合SPU时必须填写已有组合SPU编号';
  }
  return ({
    'This field may not be null.': '该字段不能为空',
    'This field is required.': '该字段为必填项',
    'This field may not be blank.': '该字段不能为空白',
    'A valid integer is required.': '请填写有效的整数',
  })[message] || message;
}

function fieldErrors(value, path = '', key = '') {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => fieldErrors(item, typeof item === 'object' && item !== null ? `${path}${path ? ' ' : ''}第${index + 1}项` : path, key));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([field, item]) => fieldErrors(item, [path, FIELD_LABELS[field] || field].filter(Boolean).join(' / '), field));
  }
  const message = String(value ?? '').trim();
  return message ? [`${path ? `${path}：` : ''}${readableValidationMessage(message, key)}`] : [];
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
