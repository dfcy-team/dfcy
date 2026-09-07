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

// Deep links must resolve a single tenant-scoped record instead of guessing
// from the first page of a collection.  The detail request deliberately does
// not fall back to a collection fixture after a network failure; an invalid
// deep link must remain visible as a failure rather than opening another row.
export const fetchMasterDataDetail = (resource, id) => requestWithMockFallback(
  {
    method: 'get',
    url: `/api/internal/master-data/${encodeURIComponent(resource)}/${encodeURIComponent(id)}/`,
    noMockFallback: true,
  },
  () => {
    const fixture = masterDataMocks[resource]?.();
    const rows = fixture?.data && Array.isArray(fixture.data.results) ? fixture.data.results : [];
    const item = rows.find((row) => String(row.id) === String(id));
    return item
      ? { success: true, code: 'OK', message: 'success', data: JSON.parse(JSON.stringify(item)) }
      : { success: false, code: 'MOCK_NOT_FOUND', message: '模拟数据未提供该主档记录', data: null };
  },
  `masterdata.${resource}.detail`
);
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
