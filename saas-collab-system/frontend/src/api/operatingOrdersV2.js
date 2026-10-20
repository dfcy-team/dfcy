import { requestApi } from './request';

const BASE = '/api/internal/commerce/';
const url = (id = '') => `${BASE}operating-orders/${id}`;
const write = (method, path, data, key) => requestApi({ method, url: path, data, headers: { 'Idempotency-Key': key } });

export const fetchOperatingOptions = (params) => requestApi({ method: 'get', url: `${BASE}operating-options/`, params });
export const fetchOperatingOrders = (params) => requestApi({ method: 'get', url: url(), params });
export const fetchOperatingOrder = (id) => requestApi({ method: 'get', url: url(`${encodeURIComponent(id)}/`) });
const PROCUREMENT_BASE = '/api/internal/supply-chain/v2/';
export const fetchSubmittedProcurementOrders = (params) => requestApi({ method: 'get', url: `${PROCUREMENT_BASE}operating-orders/`, params });
export const fetchSubmittedProcurementOrder = (id) => requestApi({ method: 'get', url: `${PROCUREMENT_BASE}operating-orders/${encodeURIComponent(id)}/` });
export const splitOperatingOrder = (id, data, key) => write('post', `${PROCUREMENT_BASE}operating-orders/${encodeURIComponent(id)}/split/`, data, key);
export const createOperatingOrder = (data, key) => write('post', url(), data, key);
export const updateOperatingOrder = (id, data, key) => write('patch', url(`${encodeURIComponent(id)}/`), data, key);
export const submitOperatingOrder = (id, data, key) => write('post', url(`${encodeURIComponent(id)}/submit/`), data, key);
export const cancelOperatingOrder = (id, data, key) => write('post', url(`${encodeURIComponent(id)}/cancel/`), data, key);
export const previewOperatingOrder = (data, key) => write('post', `${BASE}operating-orders/preview/`, data, key);
export function createIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16); });
}

export const fetchOperatingReferences = (data) => requestApi({ method: 'post', url: `${BASE}operating-orders/references/`, data });
