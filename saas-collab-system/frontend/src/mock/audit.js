import { successResponse } from './index';

export const mockOperationLogs = () => successResponse({
  status: 'mock',
  module: 'audit.operation_logs',
  items: [
    {
      operator: 'mock-user',
      module: 'mock-module',
      action: 'mock-action',
      object_id: 'mock-object-001'
    }
  ]
});
