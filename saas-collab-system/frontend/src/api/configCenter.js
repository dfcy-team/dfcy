import { requestWithMockFallback } from './request';
import { mockConfigItems, mockConfigVersions } from '../mock/configCenter';

export const fetchConfigItems = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/config/items/', params },
    mockConfigItems,
    'config.items'
  );

export const fetchConfigVersions = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/config/versions/', params },
    mockConfigVersions,
    'config.versions'
  );
