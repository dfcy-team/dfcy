import { requestWithMockFallback } from './request';
import { mockRpaTaskDetail, mockRpaTasks } from '../mock/rpa';

// Frontend RPA management uses internal pending query APIs only.
// Agent execution endpoints under /api/rpa/* require backend-issued agent auth and are never called here.
export const fetchRpaTasks = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/tasks/', params }, mockRpaTasks, 'rpa.tasks');

export const fetchRpaTaskDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/rpa/tasks/${id}/` }, mockRpaTaskDetail, 'rpa.tasks.detail');

export const assignRpaManual = (id, payload = {}) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/rpa/tasks/${id}/assign-manual/`, data: payload },
    mockRpaTaskDetail,
    'rpa.tasks.assign_manual'
  );

export const retryRpaMock = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/rpa/tasks/${id}/retry-mock/` },
    mockRpaTaskDetail,
    'rpa.tasks.retry_mock'
  );
