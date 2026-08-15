import { requestWithMockFallback } from './request';
import {
  mockFreezeProductCode,
  mockProductMasterDetail,
  mockProductMasterList,
  mockProductSkuList,
  mockProductStatusList,
  mockResearchDetail,
  mockResearchList
} from '../mock/products';

export const fetchResearchList = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/research/', params }, mockResearchList, 'products.research');

export const fetchResearchDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/products/research/${id}/` }, mockResearchDetail, 'products.research.detail');

export const fetchProductMasterList = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/spus/', params }, mockProductMasterList, 'products.spus');

export const fetchProductMasterDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/products/spus/${id}/` }, mockProductMasterDetail, 'products.spus.detail');

export const fetchProductSkuList = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/skus/', params }, mockProductSkuList, 'products.skus');

export const freezeProductCode = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/products/spus/${id}/freeze-code/` },
    mockFreezeProductCode,
    'products.spus.freeze_code'
  );

export const fetchProductStatusList = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/spus/', params }, mockProductStatusList, 'products.status');

export const fetchProductCategories = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/categories/', params }, () => ({ success: true, data: [] }), 'products.categories');

export const fetchProductColors = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/colors/', params }, () => ({ success: true, data: [] }), 'products.colors');

export const fetchProductAttributes = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/attributes/', params }, () => ({ success: true, data: [] }), 'products.attributes');

export const fetchLegacyProductItems = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/legacy-items/', params }, () => ({ success: true, data: [] }), 'products.legacy_items');

export const importLegacyProductItems = (csv) =>
  requestWithMockFallback({ method: 'post', url: '/api/internal/products/legacy-items/', data: { csv } }, () => ({ success: false }), 'products.legacy_items.import');

export const updateLegacyProductItem = (id, data) =>
  requestWithMockFallback({ method: 'patch', url: `/api/internal/products/legacy-items/${id}/`, data }, () => ({ success: false }), 'products.legacy_items.update');

export const generateLegacyProductItem = (id) =>
  requestWithMockFallback({ method: 'post', url: `/api/internal/products/legacy-items/${id}/generate/` }, () => ({ success: false }), 'products.legacy_items.generate');
