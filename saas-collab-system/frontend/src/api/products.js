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

export const fetchResearchList = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/research/' }, mockResearchList, 'products.research');

export const fetchResearchDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/products/research/${id}/` }, mockResearchDetail, 'products.research.detail');

export const fetchProductMasterList = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/spus/' }, mockProductMasterList, 'products.spus');

export const fetchProductMasterDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/products/spus/${id}/` }, mockProductMasterDetail, 'products.spus.detail');

export const fetchProductSkuList = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/skus/' }, mockProductSkuList, 'products.skus');

export const freezeProductCode = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/products/spus/${id}/freeze-code/` },
    mockFreezeProductCode,
    'products.spus.freeze_code'
  );

export const fetchProductStatusList = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/spus/' }, mockProductStatusList, 'products.status');
