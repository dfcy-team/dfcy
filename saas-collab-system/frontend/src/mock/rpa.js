import { rpaStatuses, rpaTaskTypes, successResponse } from './index';

const payload = {
  product_code: 'MOCK-PRODUCT-001',
  sku_code: 'MOCK-SKU-001',
  platform: 'mock-platform',
  action: 'demo-only',
  selector_profile: 'PLACEHOLDER_SELECTOR_PROFILE'
};

const result = {
  status: 'manual_required',
  message: 'mock result only',
  screenshots: ['https://example.invalid/demo-rpa-screenshot-001.png'],
  page_url: 'https://example.invalid/demo-rpa-page',
  page_snapshot: 'demo page snapshot placeholder',
  error_code: 'MOCK_MANUAL_REQUIRED',
  error_message: 'mock manual review required'
};

const logs = [
  {
    log_id: 'mock-log-001',
    level: 'info',
    step_name: 'mock_open_page',
    message: 'mock step log only',
    occurred_at: '2026-07-10T00:00:00Z'
  }
];

const screenshots = [
  {
    screenshot_id: 'mock-shot-001',
    step_name: 'mock_manual_check',
    screenshot_url: 'https://example.invalid/demo-rpa-screenshot-001.png',
    message: 'demo screenshot url only'
  }
];

const task = {
  id: 1,
  task_id: 'mock-rpa-task-001',
  task_type: 'BIGSELLER_CREATE_PRODUCT',
  business_type: 'product_master',
  business_id: 'mock-business-001',
  status: 'manual_required',
  agent: 'mock-agent-placeholder',
  retry_count: 1,
  payload,
  result,
  screenshots,
  logs,
  error_message: 'mock manual review required',
  manual_required: true
};

export const mockRpaTasks = () => successResponse({
  status: 'mock',
  module: 'rpa.tasks.pending',
  statuses: rpaStatuses,
  task_types: rpaTaskTypes,
  items: [task]
});

export const mockRpaTaskDetail = () => successResponse({
  status: 'mock',
  module: 'rpa.tasks.detail.pending',
  ...task
});
