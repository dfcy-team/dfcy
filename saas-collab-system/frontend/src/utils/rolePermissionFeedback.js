const FIELD_LABELS = {
  permission_codes: '权限',
  menu_permission_codes: '菜单权限',
  action_permission_codes: '功能操作权限',
  field_permission_codes: '字段权限',
  scope_type: '数据范围',
  scope_config: '业务范围',
  platform_ids: '平台',
  site_ids: '国家/站点',
  store_ids: '店铺',
  warehouse_ids: '仓库',
  supplier_ids: '供应商',
  non_field_errors: '',
  detail: '',
  errors: '',
};

function validationMessages(value, path = []) {
  if (typeof value === 'string' && value.trim()) {
    const label = path.map((key) => FIELD_LABELS[key] ?? key).filter(Boolean).join(' / ');
    return [label ? `${label}：${value.trim()}` : value.trim()];
  }
  if (Array.isArray(value)) return value.flatMap((item) => validationMessages(item, path));
  if (!value || typeof value !== 'object') return [];
  return Object.entries(value).flatMap(([key, item]) => validationMessages(item, [...path, key]));
}

export function roleSaveErrorMessage(response) {
  const details = [...new Set(validationMessages(response?.data))].slice(0, 3);
  if (details.length) return details.join('；');
  return response?.message || '保存失败，请检查权限和业务范围配置。';
}

export function selectedPermissionCount(menu, selectedCodes = []) {
  const selected = new Set(selectedCodes);
  return (menu?.children || []).reduce(
    (count, item) => count + (item.permissions || []).filter((permission) => selected.has(permission.code)).length,
    0,
  );
}
