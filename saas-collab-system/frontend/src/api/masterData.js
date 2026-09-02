import { requestWithMockFallback } from './request';
import { masterDataMocks } from '../mock/masterData';

const resourceRequest = (resource, params = {}) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/master-data/${resource}/`, params },
  masterDataMocks[resource],
  `masterdata.${resource}`
);

export const fetchPlatforms = (params = {}) => resourceRequest('platforms', params);
export const fetchPlatformCatalog = () => requestWithMockFallback(
  { method: 'get', url: '/api/internal/master-data/platforms/catalog/' },
  masterDataMocks.platformCatalog,
  'masterdata.platforms.catalog'
);
export const fetchStores = (params = {}) => resourceRequest('stores', params);
export const fetchWarehouses = (params = {}) => resourceRequest('warehouses', params);
export const fetchSupplierMasters = (params = {}) => resourceRequest('suppliers', params);
export const fetchCountrySites = (params = {}) => resourceRequest('sites', params);
export const fetchPlatformSites = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/master-data/platform-sites/', params },
  masterDataMocks.platformSites,
  'masterdata.platform-sites'
);

export const fetchPlatformSiteMigrationPreview = (params = {}) => requestWithMockFallback(
  {
    method: 'get',
    url: '/api/internal/master-data/platform-sites/migration-preview/',
    params,
  },
  masterDataMocks.platformSiteMigrationPreview,
  'masterdata.platform-sites.migration-preview'
);

export const applyPlatformSiteMigration = (payload) => requestWithMockFallback(
  {
    method: 'post',
    url: '/api/internal/master-data/platform-sites/migration-preview/',
    data: payload,
  },
  () => masterDataMocks.applyPlatformSiteMigration(payload),
  'masterdata.platform-sites.migration-preview.apply'
);

const mockWrite = (data) => () => ({ success: true, code: 'OK', message: 'Mock操作已记录', data: { ...data, api_status: 'mock' } });

export const createMasterData = (resource, payload) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/master-data/${resource}/`, data: payload },
  mockWrite(payload), `masterdata.${resource}.create`
);
export const updateMasterDataStatus = (resource, id, status) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/master-data/${resource}/${id}/status/`, data: { status } },
  mockWrite({ id, status }), `masterdata.${resource}.status`
);
export const updateMasterData = (resource, id, payload) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/master-data/${resource}/${id}/`, data: payload },
  mockWrite({ id, ...payload }), `masterdata.${resource}.update`
);

// Deletion is intentionally exposed only for master-data resources. The
// backend rejects referenced records with STATE_CONFLICT; callers surface that
// response as a stop/deactivate instruction instead of hiding the conflict.
export const deleteMasterData = (resource, id) => requestWithMockFallback(
  { method: 'delete', url: `/api/internal/master-data/${resource}/${id}/` },
  mockWrite({ id }),
  `masterdata.${resource}.delete`
);

export const importStores = (file, { dryRun = false } = {}) => {
  const data = new FormData();
  data.append('file', file);
  if (dryRun) data.append('dry_run', 'true');
  return requestWithMockFallback(
    { method: 'post', url: '/api/internal/master-data/stores/', data, headers: { 'Content-Type': 'multipart/form-data' } },
    () => ({ success: true, code: 'OK', message: '导入完成', data: { total: 0, valid: 0, created: 0, updated: 0, errors: [], api_status: 'mock' } }),
    'masterdata.stores.import'
  );
};
