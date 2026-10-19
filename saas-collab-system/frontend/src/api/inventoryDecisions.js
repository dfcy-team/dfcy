import { requestApi } from './request';
import { createIdempotencyKey } from './operatingOrdersV2';

const BASE = '/api/internal/commerce/';
const write = (path, data, key) => requestApi({ method: 'post', url: `${BASE}${path}`, data, headers: { 'Idempotency-Key': key } });

export const fetchCountryInventoryDecisions = (params) => requestApi({ method: 'get', url: `${BASE}inventory/country-decisions/`, params, timeout: 30000 });
export const previewCountryOperatingOrder = (data, key = createIdempotencyKey()) => write('operating-orders/preview/', data, key);
export const createCountryOperatingOrder = (data, key = createIdempotencyKey()) => write('operating-orders/', data, key);
export { createIdempotencyKey };

export const evaluateCountryInventoryAlerts = payload => requestApi({ method: 'post', url: '/api/internal/commerce/inventory/country-decisions/evaluate-alerts/', data: payload });
