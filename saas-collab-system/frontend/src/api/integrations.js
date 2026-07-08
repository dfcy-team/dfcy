import { getMockResponse } from './request';
import { mockApiSyncLogs, mockApiSyncTasks } from '../mock/integrations';

export const fetchApiSyncTasks = () => getMockResponse(mockApiSyncTasks, 'integrations.sync_tasks');
export const fetchApiSyncLogs = () => getMockResponse(mockApiSyncLogs, 'integrations.sync_logs');
