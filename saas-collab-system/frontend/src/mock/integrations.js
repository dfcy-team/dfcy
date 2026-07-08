import { successResponse } from './index';

export const mockApiSyncTasks = () => successResponse({
  status: 'mock',
  module: 'integrations.sync_tasks',
  items: [
    {
      task_no: 'MOCK-SYNC-001',
      platform: 'mock-platform',
      sync_type: 'mock',
      status: 'pending'
    }
  ]
});

export const mockApiSyncLogs = () => successResponse({
  status: 'mock',
  module: 'integrations.sync_logs',
  items: [
    {
      log_no: 'MOCK-SYNC-LOG-001',
      platform: 'mock-platform',
      status: 'pending'
    }
  ]
});
