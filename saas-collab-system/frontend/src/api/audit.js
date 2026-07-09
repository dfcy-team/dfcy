import { requestWithMockFallback } from './request';
import { mockOperationLogs } from '../mock/audit';

export const fetchOperationLogs = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/audit/operation-logs/' },
    mockOperationLogs,
    'audit.operation_logs'
  );
