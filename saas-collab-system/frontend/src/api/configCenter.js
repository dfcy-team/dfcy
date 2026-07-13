import { requestWithMockFallback } from './request';
import { mockConfigItems, mockConfigVersions } from '../mock/configCenter';

export const fetchConfigItems = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/config/definitions/', params },
    mockConfigItems,
    'config.items'
  );

export const fetchConfigVersions = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/config/values/', params },
    mockConfigVersions,
    'config.versions'
  );
