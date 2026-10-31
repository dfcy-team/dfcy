import { requestApi } from './request';

const BASE = '/api/internal/supply-chain/v2/settings/number-rules/';
export const fetchSupplyNumberRules = () => requestApi({ method: 'get', url: BASE });
export const previewSupplyNumberRule = (kind, data) => requestApi({
  method: 'post', url: `${BASE}${encodeURIComponent(kind)}/preview/`, data
});
export const saveSupplyNumberRule = (kind, data, key) => requestApi({
  method: 'patch', url: `${BASE}${encodeURIComponent(kind)}/`, data,
  headers: { 'Idempotency-Key': key }
});
const ITEMS = '/api/internal/supply-chain/v2/settings/payment-items/';
export const fetchPaymentItems = () => requestApi({ method: 'get', url: ITEMS });
export const initializePaymentItems = () => requestApi({ method: 'post', url: `${ITEMS}initialize/` });
export const savePaymentItem = (id, data, key) => requestApi({ method: id ? 'patch' : 'post', url: id ? `${ITEMS}${id}/` : ITEMS, data, headers: { 'Idempotency-Key': key } });
