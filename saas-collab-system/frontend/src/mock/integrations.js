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

export const mockMarketplaceOAuthTargets = (action = 'authorize') => {
  const authorizations = [
    {
      id: 'mock-store-authorization-001',
      integration_config_id: 1,
      store_id: 1,
      store_name: 'Demo Shopee Store',
      platform: 'shopee',
      region: 'SG',
      status: 'active',
      credential_mask: { credential: 'synthetic-***', token: 'synthetic-***' },
      credential_reference_version: 1
    },
    {
      id: 'mock-store-authorization-002',
      integration_config_id: 2,
      store_id: 2,
      store_name: 'Demo TikTok Shop',
      platform: 'tiktok',
      region: 'MY',
      status: 'error',
      credential_mask: { credential: 'synthetic-***', token: 'synthetic-***' },
      credential_reference_version: 1
    }
  ];
  if (action === 'authorize') {
    return successResponse({
      action,
      configs: [
        { id: 1, platform: 'shopee', account_alias: 'demo-shopee', environment: 'mock', status: 'disabled' },
        { id: 2, platform: 'tiktok', account_alias: 'demo-tiktok', environment: 'mock', status: 'disabled' }
      ],
      stores: [
        { store_id: 1, store_name: 'Demo Shopee Store', platform: 'shopee', region: 'SG' },
        { store_id: 2, store_name: 'Demo TikTok Shop', platform: 'tiktok', region: 'MY' }
      ],
      api_status: 'mock'
    });
  }
  return successResponse({ action, authorizations, api_status: 'mock' });
};

export const mockMarketplaceOAuthInitiate = () => successResponse({
  attempt_id: 'mock-oauth-attempt-001',
  platform: 'shopee',
  store_id: 1,
  region: 'SG',
  status: 'initiated',
  expires_at: '2099-01-01T00:05:00Z',
  request_id: 'mock-request-001',
  contract_version: 'a2-synthetic-v1',
  authorization_url: '/integrations/oauth?oauth_result=success&attempt_id=mock-oauth-attempt-001',
  api_status: 'mock'
});

export const mockMarketplaceOAuthStatus = (id = 'mock-oauth-attempt-001') => successResponse({
  attempt_id: id,
  platform: 'shopee',
  store_id: 1,
  region: 'SG',
  status: 'pending',
  expires_at: '2099-01-01T00:05:00Z',
  consumed_at: null,
  last_error_code: '',
  request_id: 'mock-request-001',
  contract_version: 'a2-synthetic-v1',
  api_status: 'mock'
});

export const mockMarketplaceOAuthAction = () => successResponse({
  status: 'pending',
  api_status: 'mock',
  message: 'Synthetic action placeholder; no platform request was sent.'
});

export const mockMarketplaceOAuthRetry = () => mockMarketplaceOAuthInitiate();
