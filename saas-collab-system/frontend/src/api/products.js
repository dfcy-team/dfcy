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

export const fetchProductDetailList = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/details/', params }, [], 'products.details');
export const bulkUpdateProductDetails = (data) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/products/details/bulk-update/', data },
  {},
  'products.details.bulk_update'
);
export const bulkCacheProductImages = (data) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/products/details/images/bulk-cache/', data, timeout: 120000 },
  {},
  'products.details.images.bulk_cache'
);

export const createProductSpu = (data) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/products/spus/', data }, {}, 'products.spus.create'
);
export const updateProductSpu = (id, data) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/products/spus/${id}/`, data }, {}, 'products.spus.update'
);
export const bulkUpdateProductSpus = (data) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/products/spus/bulk-update/', data }, {}, 'products.spus.bulk_update'
);
export const createProductSku = (data) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/products/skus/', data }, {}, 'products.skus.create'
);
export const updateProductSku = (id, data) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/products/skus/${id}/`, data }, {}, 'products.skus.update'
);
export const deleteProductSku = (id) => requestWithMockFallback(
  { method: 'delete', url: `/api/internal/products/skus/${id}/` }, {}, 'products.skus.delete'
);

const dictionaryApi = (resource) => `/api/internal/products/${resource}/`;
export const fetchProductCategories = (params = {}) => requestWithMockFallback({ method: 'get', url: dictionaryApi('categories'), params }, [], 'products.categories');
export const createProductCategory = (data) => requestWithMockFallback({ method: 'post', url: dictionaryApi('categories'), data }, {}, 'products.categories.create');
export const updateProductCategory = (id, data) => requestWithMockFallback({ method: 'patch', url: `${dictionaryApi('categories')}${id}/`, data }, {}, 'products.categories.update');
export const deleteProductCategory = (id) => requestWithMockFallback({ method: 'delete', url: `${dictionaryApi('categories')}${id}/` }, {}, 'products.categories.delete');
export const updateProductAttributes = (id, attributes) => requestWithMockFallback({ method: 'put', url: `${dictionaryApi('categories')}${id}/attributes/`, data: { attributes } }, {}, 'products.categories.attributes');

export const fetchProductColors = (params = {}) => requestWithMockFallback({ method: 'get', url: dictionaryApi('colors'), params }, [], 'products.colors');
export const createProductColor = (data) => requestWithMockFallback({ method: 'post', url: dictionaryApi('colors'), data }, {}, 'products.colors.create');
export const updateProductColor = (id, data) => requestWithMockFallback({ method: 'patch', url: `${dictionaryApi('colors')}${id}/`, data }, {}, 'products.colors.update');
export const deleteProductColor = (id) => requestWithMockFallback({ method: 'delete', url: `${dictionaryApi('colors')}${id}/` }, {}, 'products.colors.delete');

export const fetchProductAttributes = (params = {}) => requestWithMockFallback({ method: 'get', url: dictionaryApi('attributes'), params }, [], 'products.attributes');
export const createProductAttribute = (data) => requestWithMockFallback({ method: 'post', url: dictionaryApi('attributes'), data }, {}, 'products.attributes.create');
export const updateProductAttribute = (id, data) => requestWithMockFallback({ method: 'patch', url: `${dictionaryApi('attributes')}${id}/`, data }, {}, 'products.attributes.update');
export const deleteProductAttribute = (id) => requestWithMockFallback({ method: 'delete', url: `${dictionaryApi('attributes')}${id}/` }, {}, 'products.attributes.delete');

export const fetchLegacyProductItems = (params = {}) => requestWithMockFallback({ method: 'get', url: dictionaryApi('legacy-items'), params }, [], 'products.legacy');
export const importLegacyProductItems = (csvText) => requestWithMockFallback(
  { method: 'post', url: dictionaryApi('legacy-items'), data: { csv_text: csvText }, timeout: 120000 },
  {},
  'products.legacy.import'
);
export const updateLegacyProductItem = (id, data) => requestWithMockFallback({ method: 'patch', url: `${dictionaryApi('legacy-items')}${id}/`, data }, {}, 'products.legacy.update');
export const generateLegacyProductItem = (id) => requestWithMockFallback({ method: 'post', url: `${dictionaryApi('legacy-items')}${id}/generate/` }, {}, 'products.legacy.generate');
export const createBundleComponent = (data) => requestWithMockFallback({ method: 'post', url: dictionaryApi('bundle-components'), data }, {}, 'products.bundle_components.create');

export const freezeProductCode = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/products/spus/${id}/freeze-code/` },
    mockFreezeProductCode,
    'products.spus.freeze_code'
  );

export const fetchProductStatusList = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/products/spus/', params }, mockProductStatusList, 'products.status');
