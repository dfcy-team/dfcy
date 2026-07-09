import { rpaStatuses, rpaTaskTypes, successResponse } from './index';

const mockPayload = {
  product_code: 'MOCK-PRODUCT-001',
  sku_code: 'MOCK-SKU-001',
  platform: 'mock-platform',
  action: 'demo-only',
  selector_profile: 'PLACEHOLDER_SELECTOR_PROFILE'
};

const mockResult = {
  status: 'manual_required',
  message: 'mock result only',
  screenshots: ['https://example.invalid/demo-rpa-screenshot-001.png'],
  page_url: 'https://example.invalid/demo-rpa-page',
  page_snapshot: 'demo page snapshot placeholder',
  error_code: 'MOCK_MANUAL_REQUIRED',
  error_message: 'mock manual review required'
};

const mockLogs = [
  {
    log_id: 'mock-log-001',
    level: 'info',
    step_name: 'mock_open_page',
    message: 'mock step log only',
    occurred_at: '2026-07-09T00:00:00Z'
  },
  {
    log_id: 'mock-log-002',
    level: 'warning',
    step_name: 'mock_manual_check',
    message: 'manual check placeholder',
    occurred_at: '2026-07-09T00:01:00Z'
  }
];

const mockScreenshots = [
  {
    screenshot_id: 'mock-shot-001',
    step_name: 'mock_manual_check',
    screenshot_url: 'https://example.invalid/demo-rpa-screenshot-001.png',
    message: 'demo screenshot url only'
  }
];

const mockTask = {
  id: 1,
  task_id: 'mock-rpa-task-001',
  task_type: 'BIGSELLER_CREATE_PRODUCT',
  business_type: 'product_master',
  business_id: 'mock-business-001',
  status: 'manual_required',
  agent: 'mock-agent-placeholder',
  retry_count: 1,
  payload: mockPayload,
  result: mockResult,
  screenshots: mockScreenshots,
  logs: mockLogs,
  error_message: 'mock manual review required',
  manual_required: true,
  created_at: '2026-07-09T00:00:00Z',
  completed_at: ''
};

export const mockRpaTasks = () => successResponse({
  status: 'mock',
  module: 'rpa.tasks',
  statuses: rpaStatuses,
  task_types: rpaTaskTypes,
  items: [mockTask]
});

export const mockRpaTaskDetail = () => successResponse({
  status: 'mock',
  module: 'rpa.task.detail',
  ...mockTask
});
