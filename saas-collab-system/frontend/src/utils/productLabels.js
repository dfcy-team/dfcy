// API status values remain stable machine codes; these helpers only localize
// their presentation in product master/status views.
export const PRODUCT_LIFECYCLE_STATUS_LABELS = Object.freeze({
  draft: '草稿',
  active: '在售',
  discontinued: '已停产'
});

export const PRODUCT_SALES_STATUS_LABELS = Object.freeze({
  not_listed: '未刊登',
  on_sale: '销售中',
  paused: '已暂停',
  stopped: '已停止'
});

export function productLifecycleStatusLabel(value) {
  return PRODUCT_LIFECYCLE_STATUS_LABELS[value] || value || '-';
}

export function productSalesStatusLabel(value) {
  return PRODUCT_SALES_STATUS_LABELS[value] || value || '-';
}
