import { successResponse } from './index';

const config = {
  id: 1,
  platform: 'BigSeller',
  account_alias: 'demo-account',
  environment: 'sandbox',
  status: 'security_review_required',
  credential_fingerprint: '***demo-fingerprint',
  credential_key_version: 'demo-v1',
  last_verified_at: '',
  updated_at: '2026-07-10T00:00:00Z'
};

const syncJob = {
  id: 1,
  resource_type: 'product_listing',
  schedule_type: 'manual',
  status: 'pending',
  is_enabled: false,
  last_run_at: '',
  next_run_at: '',
  retry_count: 0
};

const syncRun = {
  id: 1,
  run_id: 'MOCK-RUN-001',
  platform: 'BigSeller',
  resource_type: 'product_listing',
  status: 'failed',
  started_at: '2026-07-10T00:00:00Z',
  finished_at: '2026-07-10T00:01:00Z',
  fetched_count: 20,
  created_count: 0,
  updated_count: 0,
  skipped_count: 20,
  failed_count: 1,
  retry_count: 1,
  error_code: 'MOCK_MASKED_ERROR',
  masked_error_message: 'demo masked error, credential and token removed'
};

export const mockIntegrationConfigs = () => successResponse({
  status: 'mock',
  module: 'integrations.configs',
  items: [config]
});

export const mockIntegrationConfigDetail = () => successResponse({
  status: 'mock',
  module: 'integrations.configs.detail',
  ...config
});

export const mockSyncJobs = () => successResponse({
  status: 'mock',
  module: 'integrations.sync_jobs',
  items: [syncJob]
});

export const mockSyncRuns = () => successResponse({
  status: 'mock',
  module: 'integrations.sync_runs',
  items: [syncRun]
});

export const mockSyncRunDetail = () => successResponse({
  status: 'mock',
  module: 'integrations.sync_runs.detail',
  ...syncRun,
  quality_check_result: {
    valid_count: 19,
    invalid_count: 1,
    masked_error: 'demo masked quality issue'
  }
});

export const mockApiSyncTasks = mockSyncJobs;
export const mockApiSyncLogs = mockSyncRuns;
