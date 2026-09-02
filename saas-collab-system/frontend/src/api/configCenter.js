import { requestApi, requestWithMockFallback } from './request';
import { mockConfigChangeLogs, mockConfigDefinitions, mockConfigValues } from '../mock/configCenter';

export const fetchConfigDefinitions = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/config/definitions/', params },
    mockConfigDefinitions,
    'config.definitions'
  ).then((response) => {
    // The definition endpoint predates paginated envelopes and returns a
    // plain list in ``data``.  Normalize it for the decision page while
    // preserving the explicit connected/mock capability signal.
    if (!response?.success || !Array.isArray(response.data)) return response;
    return {
      ...response,
      data: { items: response.data, api_status: 'connected' }
    };
  });

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
