import { requestApi } from './request';

export const fetchProductCosts = (params = {}) => requestApi({ method: 'get', url: '/api/internal/products/costs/', params });

export const createProductCostVersion = (data) => requestApi({ method: 'post', url: '/api/internal/products/costs/versions/', data });

export const previewProductCostBackfill = (data = {}) => requestApi({ method: 'post', url: '/api/internal/products/costs/backfill-preview/', data });
export const executeProductCostBackfill = (data = {}) => requestApi({ method: 'post', url: '/api/internal/products/costs/backfill-execute/', data });
export const confirmProductCostVersion = (id, data = {}) => requestApi({ method: 'post', url: `/api/internal/products/costs/versions/${id}/confirm/`, data });

const importPayload = (file, confirm = false, token = '') => {
  const data = new FormData();
  data.append('file', file);
  data.append('dry_run', confirm ? 'false' : 'true');
  if (token) data.append('token', token);
  return data;
};

export const previewProductCostImport = (file) => requestApi({ method: 'post', url: '/api/internal/products/costs/import/preview/', data: importPayload(file), timeout: 120000 });

export const confirmProductCostImport = (file, token, idempotencyKey) => requestApi({ method: 'post', url: '/api/internal/products/costs/import/confirm/', data: importPayload(file, true, token), headers: { 'Idempotency-Key': idempotencyKey }, timeout: 120000 });
