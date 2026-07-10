import { requestWithMockFallback } from './request';
import { mockApiSyncLogs, mockApiSyncTasks } from '../mock/integrations';

export const fetchApiSyncTasks = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-tasks/' },
    mockApiSyncTasks,
    'integrations.sync_tasks'
  );

export const fetchApiSyncLogs = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-logs/' },
    mockApiSyncLogs,
    'integrations.sync_logs'
  );
