import { requestWithMockFallback } from './request';
import { mockRpaTaskDetail, mockRpaTasks } from '../mock/rpa';

// Frontend RPA management uses internal APIs only.
// Agent execution endpoints under /api/rpa/* require backend-issued agent auth and are not called here.
export const fetchRpaTasks = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/tasks/' }, mockRpaTasks, 'rpa.tasks');

export const fetchRpaTaskDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/rpa/tasks/${id}/` }, mockRpaTaskDetail, 'rpa.task.detail');
