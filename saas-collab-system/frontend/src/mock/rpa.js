import { rpaStatuses, rpaTaskTypes, successResponse } from './index';

export const mockRpaTasks = () => successResponse({
  status: 'mock',
  module: 'rpa.tasks',
  statuses: rpaStatuses,
  task_types: rpaTaskTypes,
  items: [
    {
      task_id: 'mock-rpa-task-001',
      task_type: 'BIGSELLER_CREATE_PRODUCT',
      task_status: 'pending',
      business_id: 'mock-business-001'
    }
  ]
});

export const mockRpaTaskDetail = () => successResponse({
  status: 'mock',
  module: 'rpa.task.detail',
  task_id: 'mock-rpa-task-001',
  payload: {},
  result: null
});
