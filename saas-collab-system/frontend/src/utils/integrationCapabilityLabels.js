export const capabilityNames = Object.freeze({
  PRODUCT: '商品',
  CATEGORY: '类目',
  LISTING: '刊登',
  PRICE: '价格',
  ORDER: '订单',
  INVENTORY: '库存',
  FULFILLMENT: '履约',
  WAREHOUSE: '仓储',
  RETURN_REFUND: '退货退款',
  SETTLEMENT: '结算',
  PAYMENT: '收款',
  ADVERTISING: '广告',
  AFFILIATE: '联盟营销',
  REVIEW: '评价',
  REPORT: '报表',
  WEBHOOK: '事件通知',
});

export const apiTypeNames = Object.freeze({
  marketplace: '商城销售 API',
  advertising: '广告 API',
  inventory: '库存 API',
});

export function capabilityLabel(code) {
  return `${code} · ${capabilityNames[code] || code}`;
}

export function authorizationSourceLabel(authorization) {
  const purpose = apiTypeNames[authorization?.api_type] || '平台 API';
  const account = authorization?.account_alias || `接入配置 #${authorization?.integration_config_id || '—'}`;
  return `${purpose} · ${account} · 授权 #${authorization?.id || '—'}`;
}
