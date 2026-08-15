import { requestApi, requestWithMockFallback } from './request';

const mock = (data = {}) => ({ success: true, code: 'OK', message: 'mock', data });
export const fetchPlatformProductDetails = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/listings/product-details/', params },
  () => mock({ results: [], count: 0, next: null, previous: null }),
  'listings.product_detail.view'
);
export const createPlatformProductDetail = (payload) => requestApi({ method: 'post', url: '/api/internal/listings/product-details/', data: payload });
export const updatePlatformProductDetail = (id, payload) => requestApi({ method: 'patch', url: `/api/internal/listings/product-details/${id}/`, data: payload });
export const importPlatformProductDetails = (file, { dryRun = false, platform = '' } = {}) => {
  const data = new FormData(); data.append('file', file); data.append('dry_run', String(dryRun)); if (platform) data.append('platform', platform);
  return requestApi({ method: 'post', url: '/api/internal/listings/product-details/import/', data });
};
