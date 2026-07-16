import { requestWithMockFallback } from './request';
import { masterDataMocks } from '../mock/masterData';

const resourceRequest = (resource, params = {}) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/master-data/${resource}/`, params },
  masterDataMocks[resource],
  `masterdata.${resource}`
);

export const fetchPlatforms = (params = {}) => resourceRequest('platforms', params);
export const fetchStores = (params = {}) => resourceRequest('stores', params);
export const fetchWarehouses = (params = {}) => resourceRequest('warehouses', params);
export const fetchSupplierMasters = (params = {}) => resourceRequest('suppliers', params);

const mockWrite = (data) => () => ({ success: true, code: 'OK', message: 'Mock操作已记录', data: { ...data, api_status: 'mock' } });

export const createMasterData = (resource, payload) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/master-data/${resource}/`, data: payload },
  mockWrite(payload), `masterdata.${resource}.create`
);
export const updateMasterDataStatus = (resource, id, status) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/master-data/${resource}/${id}/status/`, data: { status } },
  mockWrite({ id, status }), `masterdata.${resource}.status`
);
