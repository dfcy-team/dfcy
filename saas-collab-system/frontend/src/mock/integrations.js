import { successResponse } from './index';

const config = {
  id: 1,
  platform: 'shopee',
  account_alias: 'Shopee 东南亚测试应用',
  environment: 'sandbox',
  status: 'configured',
  regions: ['PH', 'TH', 'MY'],
  contract_version: 'v2',
  callback_url: 'https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/shopee/',
  scopes: [],
  platform_config: { partner_id: 'partner-***' },
  connect_timeout_seconds: 3,
  read_timeout_seconds: 8,
  network_enabled: false,
  sync_read_enabled: false,
  sync_write_enabled: false,
  config_version: 1,
  credential_status: 'configured',
  credential_mask: { configured: '********' },
  credential_reference_version: 1,
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

export const mockIntegrationConfigSchema = (platform = 'shopee', environment = 'sandbox') => successResponse({
  platform,
  environment,
  contract_versions: platform === 'tiktok' ? ['202407'] : ['v2'],
  environments: [
    { value: 'sandbox', label: 'Sandbox' },
    { value: 'pilot', label: 'Pilot' },
    { value: 'production', label: 'Production（需审批）' }
  ],
  regions: [
    { value: 'PH', label: '菲律宾 (PH)' },
    { value: 'TH', label: '泰国 (TH)' },
    { value: 'MY', label: '马来西亚 (MY)' }
  ],
  scope_options: platform === 'tiktok'
    ? [{ value: 'seller.authorization.info', label: '店铺授权信息（只读）' }]
    : [],
  public_fields: platform === 'tiktok'
    ? [{ key: 'app_key', label: 'App Key', required: true }]
    : [{ key: 'partner_id', label: 'Partner ID', required: true }],
  secret_fields: [
    { key: 'app_secret', label: 'App Secret' },
    { key: 'access_token', label: 'Access Token' },
    { key: 'refresh_token', label: 'Refresh Token' }
  ],
  timeout_limits: { connect: { min: 1, max: 10 }, read: { min: 1, max: 30 } }
});

export const mockIntegrationAudit = () => successResponse([
  {
    id: 1,
    action: 'rotate_credential',
    actor_id: 1,
    result: 'success',
    masked_detail: { credential_mask: { configured: '********' }, reference_version: 1 },
    created_at: '2026-08-08T00:00:00Z'
  }
]);

export const mockMarketplaceStoreAuthorizations = () => successResponse({
  status: 'mock',
  count: 0,
  next: null,
  previous: null,
  results: []
});

export const mockMarketplaceAuthorizationStart = () => successResponse({
  status: 'pending/mock',
  authorization_url: '',
  expires_at: ''
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
