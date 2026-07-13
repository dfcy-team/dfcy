import { requestApi, requestWithMockFallback } from './request';
import { mockConfigChangeLogs, mockConfigDefinitions, mockConfigValues } from '../mock/configCenter';

export const fetchConfigDefinitions = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/config/definitions/', params },
    mockConfigDefinitions,
    'config.definitions'
  );

export const fetchConfigValues = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/config/values/', params },
    mockConfigValues,
    'config.values'
  );

export const createConfigValue = (payload) => requestApi({ method: 'post', url: '/api/internal/config/values/', data: payload });
export const approveConfigValue = (id) => requestApi({ method: 'post', url: `/api/internal/config/values/${id}/approve/` });
export const rollbackConfigValue = (id, payload = {}) => requestApi({ method: 'post', url: `/api/internal/config/values/${id}/rollback/`, data: payload });
export const fetchConfigChangeLogs = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/config/change-logs/', params }, mockConfigChangeLogs, 'config.change_logs'
);
