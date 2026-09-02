import { requestWithMockFallback } from './request';
import {
  mockFreezeProductCode,
  mockProductMasterDetail,
  mockProductMasterList,
  mockProductDetailList,
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

export const createProductSpu = (data = {}) =>
  requestWithMockFallback({ method: 'post', url: '/api/internal/products/spus/', data }, () => ({
    success: true,
    code: 'OK',
    message: '商品已创建（模拟）',
    data: { id: `mock-${Date.now()}`, product_name: data.product_name, category_node: data.category_node, spu_code: 'MOCK-SPU-NEW' }
  }), 'products.spus.create');

export const fetchCodingOptions = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/coding-options/' }, () => ({
    success: true,
    data: { seasons: [], product_types: [] }
  }), 'products.coding_options');

export const fetchProductMasterDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/products/spus/${id}/` }, mockProductMasterDetail, 'products.spus.detail');

export const fetchProductSkuList = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/skus/', params }, mockProductSkuList, 'products.skus');

export const fetchProductDetailList = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/products/details/', params },
    mockProductDetailList,
    'products.details'
  );

export const createProductSku = (data = {}) =>
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/products/skus/', data },
    () => ({
      success: true,
      code: 'OK',
      message: 'SKU 已生成（模拟）',
      data: {
        id: `mock-${Date.now()}`,
        spu: data.spu,
        color_code: data.color_code,
        spec_values: data.spec_values || {},
        sku_code: 'MOCK-SKU-NEW'
      }
    }),
    'products.skus.create'
  );

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
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/products/legacy-items/', data: { csv_text: csv } },
    () => ({ success: false }),
    'products.legacy_items.import'
  );

export const updateLegacyProductItem = (id, data) =>
  requestWithMockFallback({ method: 'patch', url: `/api/internal/products/legacy-items/${id}/`, data }, () => ({ success: false }), 'products.legacy_items.update');

export const generateLegacyProductItem = (id) =>
  requestWithMockFallback({ method: 'post', url: `/api/internal/products/legacy-items/${id}/generate/` }, () => ({ success: false }), 'products.legacy_items.generate');
