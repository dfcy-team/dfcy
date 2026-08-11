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
