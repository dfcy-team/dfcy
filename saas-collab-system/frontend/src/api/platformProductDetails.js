import { requestApi, requestWithMockFallback } from './request';
import {
  mockCreatePlatformProductDetail,
  mockPlatformProductDetails,
  mockUpdatePlatformProductDetail,
} from '../mock/mappings';

export const PLATFORM_PRODUCT_DETAIL_PAGE_SIZE = 20;
export const fetchPlatformProductDetails = ({ page = 1, page_size = PLATFORM_PRODUCT_DETAIL_PAGE_SIZE, ...params } = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/listings/product-details/', params: { ...params, page, page_size }, noMockFallback: true },
  () => mockPlatformProductDetails({ ...params, page, page_size }),
  'listings.product_detail.view'
);
export const createPlatformProductDetail = (payload) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/listings/product-details/', data: payload },
  () => mockCreatePlatformProductDetail(payload),
  'listings.product_detail.create'
);
export const updatePlatformProductDetail = (id, payload) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/listings/product-details/${id}/`, data: payload },
  () => mockUpdatePlatformProductDetail(id, payload),
  'listings.product_detail.update'
);
export const bulkUpdatePlatformProductDetails = (payload) => requestApi({ method: 'post', url: '/api/internal/listings/product-details/bulk-update/', data: payload });
export const importPlatformProductDetails = (file, { dryRun = false, platform = '' } = {}) => {
  const data = new FormData(); data.append('file', file); data.append('dry_run', String(dryRun)); if (platform) data.append('platform', platform);
  return requestApi({ method: 'post', url: '/api/internal/listings/product-details/import/', data, timeout: 120000 });
};
export const importPlatformProductIds = (file, { dryRun = false } = {}) => {
  const data = new FormData(); data.append('file', file); data.append('dry_run', String(dryRun));
  return requestApi({ method: 'post', url: '/api/internal/listings/product-details/import-platform-product-ids/', data, timeout: 120000 });
};
