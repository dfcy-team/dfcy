import { getMockResponse } from './request';
import { mockOperationLogs } from '../mock/audit';

export const fetchOperationLogs = () => getMockResponse(mockOperationLogs, 'audit.operation_logs');
