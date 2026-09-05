import { successResponse } from './index';

const config = {
  id: 1,
  platform: 'shopee',
  account_alias: 'demo-shopee',
  environment: 'sandbox',
  status: 'active',
  regions: ['SG'],
  callback_url: 'https://sandbox.example.invalid/api/internal/integrations/store-authorizations/oauth/callback/shopee/',
  scopes: ['shop.info', 'order.read'],
  api_type: 'marketplace',
  credential_status: 'referenced',
  credential_fingerprint: '***demo-fingerprint',
  credential_key_version: 'demo-v1',
  contract_version: 'shopapi-local-v1',
  config_version: 1,
  credential_reference_version: 'demo-v1',
  reference_count: 3,
  last_verified_at: '2026-09-01T09:00:00Z',
  updated_at: '2026-09-01T10:00:00Z'
};

// This is the safe, non-network Shopee fixture used by the platform drill.
// It deliberately contains only references and masked metadata, never secrets.
const shopeeSandboxConfig = {
  id: 2,
  platform: 'shopee',
  account_alias: 'demo-shopee-secondary',
  environment: 'sandbox',
  status: 'active',
  credential_status: 'referenced',
  credential_fingerprint: '***demo-shopee-fingerprint',
  credential_key_version: 'demo-v1',
  callback_url: 'https://sandbox.example.test/oauth/callback/shopee',
  scopes: ['read_orders', 'read_products'],
  regions: ['SG', 'MY'],
  api_type: 'marketplace',
  contract_version: 'shopapi-local-v1',
  config_version: 1,
  credential_reference_version: 'demo-v1',
  reference_count: 0,
  last_verified_at: '2026-09-01T09:00:00Z',
  updated_at: '2026-09-01T09:00:00Z'
};

const jifengInventoryConfig = {
  id: 3,
  platform: 'jifeng_wms',
  account_alias: 'demo-wms',
  environment: 'pilot',
  status: 'verified',
  credential_status: 'referenced',
  credential_fingerprint: '***demo-wms-fingerprint',
  credential_key_version: 'demo-v1',
  contract_version: 'jifeng-wms-local-v1',
  config_version: 1,
  credential_reference_version: 'demo-v1',
  reference_count: 1,
  last_verified_at: '2026-09-01T09:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  regions: ['MY'],
  api_type: 'inventory'
};

const configFixtures = [config, shopeeSandboxConfig, jifengInventoryConfig];

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
  platform: 'shopee',
  resource_type: 'sales_order',
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
  items: configFixtures.map((item) => ({ ...item }))
});

export const mockIntegrationConfigDetail = (id = 1) => {
  const item = configFixtures.find((candidate) => String(candidate.id) === String(id)) || config;
  return successResponse({
    status: 'mock',
    module: 'integrations.configs.detail',
    ...item
  });
};

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

// The workspace response mirrors integration_workspace() so the sync-jobs page
// can exercise health and scheduling states without inventing a second shape.
const workspaceJobs = [
  {
    id: 1,
    platform: 'shopee',
    api_type: 'marketplace',
    account_alias: 'demo-shopee',
    config_name: 'demo-shopee',
    config_status: 'active',
    credential_status: 'referenced',
    resource_type: 'sales_order',
    schedule_type: 'hourly',
    execution_mode: 'live_readonly',
    status: 'failed',
    is_enabled: true,
    max_retry_count: 3,
    backoff_base_seconds: 2,
    query_mode: 'incremental',
    lookback_days: 30,
    overlap_minutes: 5,
    query_page_size: 50,
    max_pages: 100,
    max_records: 50000,
    range_start_at: null,
    range_end_at: null,
    interval_minutes: 60,
    local_time: '02:00',
    weekdays: [1, 2, 3, 4, 5, 6, 7],
    timezone: 'Asia/Shanghai',
    catch_up: 'run_once',
    pause_until: null,
    query_statuses: [],
    token_policy: 'auto_refresh',
    data_destination: '销售订单',
    data_table: 'sales_orders',
    last_run_at: '2026-09-01T10:00:00Z',
    next_run_at: null,
    schedule_state: 'retry_exhausted',
    health_state: 'failed',
    blocked_reason: '',
    capability_state: 'ready',
    capability_code: 'ORDER',
    source_priority: 10,
    integration_config_id: 1,
    selected_authorization_id: 201,
    latest_run_status: 'failed',
    latest_run_id: 'MOCK-RUN-ORDER-001',
    latest_started_at: '2026-09-01T09:59:00Z',
    latest_finished_at: '2026-09-01T10:00:00Z',
    latest_fetched_count: 120,
    latest_created_count: 118,
    latest_updated_count: 0,
    latest_skipped_count: 2,
    latest_failed_count: 1,
    latest_retry_count: 3,
    latest_error_code: 'MOCK_RETRY_EXHAUSTED',
    latest_error_message: 'Synthetic masked order sync error; retry limit reached.',
    checkpoint_version: 4,
    checkpoint_watermark: '2026-09-01T09:55:00Z',
    updated_at: '2026-09-01T10:00:00Z',
    subject_type: 'store',
    subject_code: 'demo-store-sg',
    subject_name: '新加坡示例店铺',
    region: 'SG',
    authorization_status: 'active',
    external_subject_id: 'masked-external-store-001'
  },
  {
    id: 2,
    platform: 'shopee',
    api_type: 'marketplace',
    account_alias: 'demo-shopee',
    config_name: 'demo-shopee',
    config_status: 'active',
    credential_status: 'referenced',
    resource_type: 'refund_return',
    schedule_type: 'hourly',
    execution_mode: 'live_readonly',
    status: 'idle',
    is_enabled: true,
    max_retry_count: 3,
    backoff_base_seconds: 2,
    query_mode: 'incremental',
    lookback_days: 30,
    overlap_minutes: 5,
    query_page_size: 50,
    max_pages: 100,
    max_records: 50000,
    range_start_at: null,
    range_end_at: null,
    interval_minutes: 60,
    local_time: '02:00',
    weekdays: [1, 2, 3, 4, 5, 6, 7],
    timezone: 'Asia/Shanghai',
    catch_up: 'run_once',
    pause_until: null,
    query_statuses: [],
    token_policy: 'auto_refresh',
    data_destination: '退货退款',
    data_table: 'refund_returns',
    last_run_at: '2026-09-01T09:10:00Z',
    next_run_at: '2026-09-01T10:10:00Z',
    schedule_state: 'retry_waiting',
    health_state: 'capability',
    blocked_reason: '所需只读能力尚未启用',
    capability_state: 'capability_missing',
    capability_code: 'RETURN_REFUND',
    source_priority: null,
    selected_authorization_id: null,
    latest_run_status: 'failed',
    latest_run_id: 'MOCK-RUN-REFUND-001',
    latest_started_at: '2026-09-01T09:09:00Z',
    latest_finished_at: '2026-09-01T09:10:00Z',
    latest_fetched_count: 18,
    latest_created_count: 17,
    latest_updated_count: 0,
    latest_skipped_count: 1,
    latest_failed_count: 1,
    latest_retry_count: 1,
    latest_error_code: 'MOCK_RETRY_WAITING',
    latest_error_message: 'Synthetic masked return sync error; next retry is scheduled.',
    checkpoint_version: 2,
    checkpoint_watermark: '2026-09-01T09:05:00Z',
    updated_at: '2026-09-01T09:10:00Z',
    subject_type: 'store',
    subject_code: 'demo-store-sg',
    subject_name: '新加坡示例店铺',
    region: 'SG',
    authorization_status: 'active',
    external_subject_id: 'masked-external-store-001'
  },
  {
    id: 3,
    platform: 'jifeng_wms',
    api_type: 'inventory',
    account_alias: 'demo-wms',
    config_name: 'demo-wms',
    config_status: 'active',
    credential_status: 'referenced',
    resource_type: 'inventory_snapshot',
    schedule_type: 'interval',
    execution_mode: 'live_readonly',
    status: 'running',
    is_enabled: true,
    max_retry_count: 3,
    backoff_base_seconds: 1,
    query_mode: 'incremental',
    lookback_days: 30,
    overlap_minutes: 5,
    query_page_size: 50,
    max_pages: 100,
    max_records: 50000,
    range_start_at: null,
    range_end_at: null,
    interval_minutes: 30,
    local_time: '02:00',
    weekdays: [1, 2, 3, 4, 5, 6, 7],
    timezone: 'Asia/Shanghai',
    catch_up: 'run_once',
    pause_until: null,
    query_statuses: [],
    token_policy: 'auto_refresh',
    data_destination: '库存快照',
    data_table: 'inventory_snapshots',
    last_run_at: '2026-09-01T09:30:00Z',
    next_run_at: '2026-09-01T10:00:00Z',
    schedule_state: 'running',
    health_state: 'running',
    blocked_reason: '',
    capability_state: 'ready',
    capability_code: 'INVENTORY',
    source_priority: 20,
    selected_authorization_id: 202,
    latest_run_status: 'running',
    latest_run_id: 'MOCK-RUN-INVENTORY-001',
    latest_started_at: '2026-09-01T09:30:00Z',
    latest_finished_at: null,
    latest_fetched_count: 0,
    latest_created_count: 0,
    latest_updated_count: 0,
    latest_skipped_count: 0,
    latest_failed_count: 0,
    latest_retry_count: 0,
    latest_error_code: '',
    latest_error_message: '',
    checkpoint_version: 7,
    checkpoint_watermark: '2026-09-01T09:29:00Z',
    updated_at: '2026-09-01T09:30:00Z',
    subject_type: 'warehouse',
    subject_code: 'MY-WMS-01',
    subject_name: '马来极风仓',
    region: 'MY',
    authorization_status: 'active',
    external_subject_id: ''
  },
  {
    id: 4,
    platform: 'shopee',
    api_type: 'marketplace',
    account_alias: 'demo-shopee',
    config_name: 'demo-shopee',
    config_status: 'active',
    credential_status: 'referenced',
    resource_type: 'settlement_bill',
    schedule_type: 'daily',
    execution_mode: 'simulation',
    status: 'disabled',
    is_enabled: false,
    max_retry_count: 3,
    backoff_base_seconds: 2,
    query_mode: 'incremental',
    lookback_days: 30,
    overlap_minutes: 5,
    query_page_size: 50,
    max_pages: 100,
    max_records: 50000,
    range_start_at: null,
    range_end_at: null,
    interval_minutes: 1440,
    local_time: '02:00',
    weekdays: [1, 2, 3, 4, 5, 6, 7],
    timezone: 'Asia/Shanghai',
    catch_up: 'run_once',
    pause_until: null,
    query_statuses: [],
    token_policy: 'auto_refresh',
    data_destination: '结算账单',
    data_table: 'settlement_bills',
    last_run_at: null,
    next_run_at: null,
    schedule_state: 'disabled',
    health_state: 'disabled',
    blocked_reason: '任务已禁用',
    capability_state: 'not_required',
    capability_code: '',
    source_priority: null,
    selected_authorization_id: null,
    latest_run_status: '',
    latest_run_id: '',
    latest_started_at: null,
    latest_finished_at: null,
    latest_fetched_count: 0,
    latest_created_count: 0,
    latest_updated_count: 0,
    latest_skipped_count: 0,
    latest_failed_count: 0,
    latest_retry_count: 0,
    latest_error_code: '',
    latest_error_message: '',
    checkpoint_version: null,
    checkpoint_watermark: null,
    updated_at: '2026-09-01T08:00:00Z',
    subject_type: 'store',
    subject_code: 'demo-store-sg',
    subject_name: '新加坡示例店铺',
    region: 'SG',
    authorization_status: 'active',
    external_subject_id: 'masked-external-store-001'
  }
];

// These rows mirror the backend _run_rows() projection. They are historical,
// redacted demonstrations only: no fixture handler performs a live request.
const workspaceRuns = [
  {
    id: 301,
    run_id: 'MOCK-RUN-LIVE-READONLY-001',
    sync_job_id: 1,
    subject_name: '新加坡示例店铺',
    subject_code: 'demo-store-sg',
    region: 'SG',
    platform: 'shopee',
    api_type: 'marketplace',
    resource_type: 'sales_order',
    data_destination: '销售订单',
    data_table: 'sales_order / sales_order_item',
    execution_mode: 'live_readonly',
    external_api_called: true,
    token_refreshed: false,
    status: 'failed',
    started_at: '2026-09-01T09:59:00Z',
    finished_at: '2026-09-01T10:00:00Z',
    duration_seconds: 60,
    fetched_count: 120,
    created_count: 0,
    updated_count: 0,
    skipped_count: 119,
    failed_count: 1,
    retry_count: 3,
    retry_of: '',
    next_retry_at: null,
    max_retry_count: 3,
    checkpoint_version: 4,
    checkpoint_advanced: false,
    archive_file_count: 1,
    error_code: 'MOCK_LIVE_READONLY_FAILED',
    masked_error_message: '本地演练：平台只读接口返回脱敏失败；未写入业务表。',
    masked_log: {
      execution_mode: 'live_readonly',
      external_api_called: true,
      token_refreshed: false,
      checkpoint: { version: 4, advanced: false },
      archive_files: ['mock-live-readonly-301.txt'],
      masked_error_message: '平台响应已脱敏并归档。'
    }
  },
  {
    id: 302,
    run_id: 'MOCK-RUN-SIMULATION-001',
    sync_job_id: 4,
    subject_name: '新加坡示例店铺',
    subject_code: 'demo-store-sg',
    region: 'SG',
    platform: 'shopee',
    api_type: 'marketplace',
    resource_type: 'settlement_bill',
    data_destination: '结算账单',
    data_table: 'settlement_bills',
    execution_mode: 'simulation',
    external_api_called: false,
    token_refreshed: false,
    status: 'failed',
    started_at: '2026-09-01T08:00:00Z',
    finished_at: '2026-09-01T08:00:05Z',
    duration_seconds: 5,
    fetched_count: 0,
    created_count: 0,
    updated_count: 0,
    skipped_count: 0,
    failed_count: 1,
    retry_count: 1,
    retry_of: '',
    next_retry_at: null,
    max_retry_count: 3,
    checkpoint_version: null,
    checkpoint_advanced: false,
    archive_file_count: 0,
    error_code: 'MOCK_SIMULATION_FAILED',
    masked_error_message: '本地演练：模拟适配器返回脱敏失败；未调用外部平台。',
    masked_log: {
      execution_mode: 'simulation',
      external_api_called: false,
      token_refreshed: false,
      stages: [
        { code: 'adapter', label: '本地模拟适配器', status: 'failed' },
        { code: 'run_failed', label: '运行结果', status: 'failed', reason: 'run_failed' }
      ],
      masked_error_message: '模拟数据校验未通过。'
    }
  }
];

const workspaceSummary = {
  config_count: configFixtures.length,
  ready_credential_count: configFixtures.length,
  store_authorization_count: 1,
  warehouse_authorization_count: 1,
  job_count: workspaceJobs.length,
  enabled_job_count: workspaceJobs.filter((job) => job.is_enabled).length,
  run_count: workspaceRuns.length,
  successful_run_count: workspaceRuns.filter((run) => run.status === 'success').length,
  failed_run_count: workspaceRuns.filter((run) => run.status === 'failed').length,
  running_run_count: workspaceRuns.filter((run) => run.status === 'running').length,
  due_job_count: 0,
  live_confirmation_job_count: 0,
  retry_waiting_job_count: 1,
  retry_exhausted_job_count: 1,
  stale_running_job_count: 1,
  capability_blocked_job_count: 1,
  open_sync_alert_count: 1,
  open_sync_incident_count: 1,
  acknowledged_sync_incident_count: 1
};

const workspaceOptions = {
  platforms: ['jifeng_wms', 'lazada', 'shopee'],
  statuses: ['active', 'configured', 'disabled', 'failed', 'idle', 'running', 'verified'],
  environments: ['sandbox', 'pilot', 'production'],
  api_types: ['advertising', 'inventory', 'marketplace'],
  resource_types: ['inventory_snapshot', 'refund_return', 'sales_order', 'settlement_bill'],
  schedule_types: ['daily', 'hourly', 'interval']
};

const workspaceReferenceOptions = {
  platforms: [
    {
      id: 11,
      value: 'shopee',
      code: 'shopee',
      name: 'Shopee',
      label: 'Shopee（shopee）',
      enabled: true,
      api_types: [
        { value: 'marketplace', label: '商城 API' },
        { value: 'advertising', label: '广告 API' }
      ],
      allowed_regions: null
    },
    {
      id: 12,
      value: 'lazada',
      code: 'lazada',
      name: 'Lazada',
      label: 'Lazada（lazada）',
      enabled: true,
      api_types: [{ value: 'marketplace', label: '商城 API' }],
      allowed_regions: ['SG', 'MY', 'TH', 'VN', 'ID', 'PH']
    },
    {
      id: 13,
      value: 'jifeng_wms',
      code: 'jifeng_wms',
      name: '极风 WMS',
      label: '极风 WMS（jifeng_wms）',
      enabled: true,
      api_types: [{ value: 'inventory', label: '库存 API' }],
      allowed_regions: null
    }
  ],
  countries: [
    { value: 'CN', country_code: 'CN', code: 'CN', name: '中国大陆', label: 'CN（中国大陆）', currency: 'CNY', timezone: 'Asia/Shanghai' },
    { value: 'SG', country_code: 'SG', code: 'SG', name: '新加坡', label: 'SG（新加坡）', currency: 'SGD', timezone: 'Asia/Singapore' },
    { value: 'MY', country_code: 'MY', code: 'MY', name: '马来西亚', label: 'MY（马来西亚）', currency: 'MYR', timezone: 'Asia/Kuala_Lumpur' },
    { value: 'TH', country_code: 'TH', code: 'TH', name: '泰国', label: 'TH（泰国）', currency: 'THB', timezone: 'Asia/Bangkok' },
    { value: 'VN', country_code: 'VN', code: 'VN', name: '越南', label: 'VN（越南）', currency: 'VND', timezone: 'Asia/Ho_Chi_Minh' },
    { value: 'ID', country_code: 'ID', code: 'ID', name: '印度尼西亚', label: 'ID（印度尼西亚）', currency: 'IDR', timezone: 'Asia/Jakarta' },
    { value: 'PH', country_code: 'PH', code: 'PH', name: '菲律宾', label: 'PH（菲律宾）', currency: 'PHP', timezone: 'Asia/Manila' }
  ],
  environments: [
    { value: 'sandbox', label: '沙箱' },
    { value: 'pilot', label: '试运行' },
    { value: 'production', label: '生产' }
  ]
};

export const mockIntegrationWorkspace = (mode = 'sync-jobs', params = {}) => {
  const results = mode === 'configs'
    ? configFixtures
    : mode === 'sync-runs'
      ? workspaceRuns
      : workspaceJobs;
  const filteredResults = results.filter((row) => {
    for (const key of ['platform', 'api_type', 'resource_type']) {
      if (params[key] && String(row[key] || '').toLowerCase() !== String(params[key]).toLowerCase()) return false;
    }
    if (params.subject) {
      const subject = String(params.subject).toLowerCase();
      const haystack = ['subject_code', 'subject_name', 'external_subject_id']
        .map((key) => String(row[key] || '').toLowerCase())
        .join(' ');
      if (!haystack.includes(subject)) return false;
    }
    return true;
  });
  return successResponse({
    mode,
    source_status: 'mock',
    api_status: 'mock',
    summary: workspaceSummary,
    scheduler: { configured: true, heartbeat_state: 'scheduled', execution_policy: 'readonly_automatic' },
    scheduler_history: [],
    options: workspaceOptions,
    reference_options: workspaceReferenceOptions,
    regions: workspaceReferenceOptions.countries,
    previews: {
      due: { due_count: workspaceSummary.due_job_count, automatic_count: 0, confirmation_count: 0, batch_limit: 20 },
      reconcile: { eligible_subject_count: 2, total_required: 3, existing_count: 3, missing_count: 0 },
      creation_available: false
    },
    pagination: { page: 1, page_size: 100, total: filteredResults.length, page_count: 1 },
    results: filteredResults.map((row) => ({ ...row }))
  });
};

const mockStoreSyncResourceRegistry = Object.freeze({
  shopee: Object.freeze(['sales_order', 'refund_return']),
  tiktok: Object.freeze(['sales_order', 'refund_return']),
  lazada: Object.freeze([]),
});
const mockWarehouseSyncResourceRegistry = Object.freeze({
  jifeng_wms: Object.freeze(['inventory_snapshot']),
});

export const mockCreateSyncJob = (payload = {}) => {
  const isWarehouse = Boolean(payload.warehouse_authorization_id);
  const authorization = isWarehouse
    ? mockWarehouseAuthorizationRows?.find?.((item) => String(item.id) === String(payload.warehouse_authorization_id))
    : mockAuthorizationRows?.find?.((item) => String(item.id) === String(payload.store_authorization_id));
  if (!authorization) return mockFailure('INVALID_AUTHORIZATION', isWarehouse ? '请选择当前配置的仓库授权' : '请选择当前配置的店铺授权');
  if (payload.integration_config_id && String(payload.integration_config_id) !== String(authorization.integration_config_id)) {
    return mockFailure('INVALID_INTEGRATION_CONFIG', '接入配置与所选授权不一致');
  }
  if (!['active', 'authorized'].includes(authorization.status)) {
    return mockFailure('AUTHORIZATION_NOT_ACTIVE', '所选授权不是 active/authorized，无法创建同步任务');
  }
  const resourceType = String(payload.resource_type || '').trim().toLowerCase();
  const platform = String(isWarehouse ? (authorization.provider || '') : (authorization.platform || '')).trim().toLowerCase();
  const supportedResources = (isWarehouse ? mockWarehouseSyncResourceRegistry : mockStoreSyncResourceRegistry)[platform] || [];
  if (!supportedResources.includes(resourceType)) {
    return mockFailure('UNSUPPORTED_RESOURCE', `${platform || '当前平台'} 未注册可创建的同步资源：${resourceType || '未指定'}`);
  }
  if (workspaceJobs.some((item) => String(item.selected_authorization_id) === String(authorization.id) && item.resource_type === resourceType)) {
    return successResponse({ idempotent: true, message: '该授权和资源已经存在同步任务', sync_job: workspaceJobs.find((item) => String(item.selected_authorization_id) === String(authorization.id) && item.resource_type === resourceType) });
  }
  const row = {
    id: Math.max(...workspaceJobs.map((item) => item.id), 0) + 1,
    integration_config_id: payload.integration_config_id,
    platform: isWarehouse ? 'jifeng_wms' : authorization.platform,
    api_type: isWarehouse ? 'inventory' : 'marketplace',
    subject_type: isWarehouse ? 'warehouse' : 'store',
    account_alias: isWarehouse ? 'demo-wms' : 'demo-shopee',
    resource_type: resourceType,
    schedule_type: payload.schedule_type || 'manual',
    execution_mode: 'simulation',
    status: 'disabled',
    is_enabled: false,
    health_state: 'disabled',
    schedule_state: 'disabled',
    blocked_reason: '任务创建后默认停用，请复核后在任务工作台启用',
    capability_state: 'ready',
    selected_authorization_id: authorization.id,
    subject_name: authorization.store_name || authorization.warehouse_name,
    region: authorization.region || authorization.country_code,
    ...(isWarehouse ? { warehouse_authorization_id: authorization.id } : { store_authorization_id: authorization.id }),
  };
  workspaceJobs.push(row);
  return successResponse(row);
};

const mockIncidentRows = [
  {
    id: 901,
    sync_job_id: 1,
    platform: 'shopee',
    resource_type: 'sales_order',
    account_alias: 'demo-shopee',
    status: 'open',
    assignee: null,
    assignee_name: null,
    acknowledged_by: null,
    acknowledged_by_name: null,
    acknowledged_at: null,
    resolved_by: null,
    resolved_by_name: null,
    resolved_at: null,
    occurrence_count: 3,
    last_sync_run_id: 301,
    last_run_id: 'MOCK-RUN-ORDER-001',
    last_error_code: 'MOCK_RETRY_EXHAUSTED',
    masked_message: 'Synthetic masked order sync error; retry limit reached.',
    resolution_note: '',
    created_at: '2026-09-01T08:00:00Z',
    updated_at: '2026-09-01T10:00:00Z'
  },
  {
    id: 902,
    sync_job_id: 2,
    platform: 'shopee',
    resource_type: 'refund_return',
    account_alias: 'demo-shopee',
    status: 'acknowledged',
    assignee: 1,
    assignee_name: 'demo-operator',
    acknowledged_by: 1,
    acknowledged_by_name: 'demo-operator',
    acknowledged_at: '2026-09-01T09:12:00Z',
    resolved_by: null,
    resolved_by_name: null,
    resolved_at: null,
    occurrence_count: 2,
    last_sync_run_id: 302,
    last_run_id: 'MOCK-RUN-REFUND-001',
    last_error_code: 'MOCK_RETRY_WAITING',
    masked_message: 'Synthetic masked return sync error; next retry is scheduled.',
    resolution_note: '已确认，等待沙箱窗口。',
    created_at: '2026-09-01T08:30:00Z',
    updated_at: '2026-09-01T09:12:00Z'
  }
];

const mockRetryPreviewByIncident = {
  901: {
    sync_job_id: 1,
    source_sync_run_id: 301,
    source_run_id: 'MOCK-RUN-ORDER-001',
    environment: 'sandbox',
    execution_mode: 'simulation',
    external_api_called: false,
    allowed: true,
    blocked_reason: '',
    requires_confirmation: true
  },
  902: {
    sync_job_id: 2,
    source_sync_run_id: 302,
    source_run_id: 'MOCK-RUN-REFUND-001',
    environment: 'production',
    execution_mode: 'simulation',
    external_api_called: false,
    allowed: false,
    blocked_reason: '人工重试仅允许 Mock 或沙箱环境。',
    requires_confirmation: true
  }
};

const mockFailure = (code, message) => ({
  success: false,
  code,
  message,
  data: null
});

const mockIncident = (id) => mockIncidentRows.find((item) => String(item.id) === String(id));

const appendIncidentNote = (incident, note) => {
  const value = String(note || '').trim();
  if (!value) return incident.resolution_note || '';
  return incident.resolution_note ? `${incident.resolution_note}；${value}` : value;
};

export const mockSyncAlertIncidents = (filters = '') => {
  const params = typeof filters === 'string' ? { status: filters } : (filters || {});
  const rows = mockIncidentRows.filter((item) => {
    if (params.status && item.status !== params.status) return false;
    if (params.store_id) {
      const job = workspaceJobs.find((entry) => String(entry.id) === String(item.sync_job_id));
      const authorization = mockAuthorizationRows.find((entry) => String(entry.id) === String(job?.selected_authorization_id));
      if (!job || String(job.store_id || authorization?.store_id) !== String(params.store_id)) return false;
    }
    return true;
  });
  return successResponse(rows.map((item) => ({ ...item })));
};

export const mockSyncAlertIncidentAction = (id, payload = {}) => {
  const incident = mockIncident(id);
  const action = String(payload.action || '').trim().toLowerCase();
  if (!incident) return mockFailure('NOT_FOUND', '同步事件不存在');
  if (!['acknowledge', 'assign', 'note', 'resolve'].includes(action)) {
    return mockFailure('INVALID_ACTION', '仅支持 acknowledge、assign、note、resolve');
  }
  const now = '2026-09-02T00:00:00Z';
  if (action === 'acknowledge') {
    incident.status = 'acknowledged';
    incident.acknowledged_by = 1;
    incident.acknowledged_by_name = 'demo-operator';
    incident.acknowledged_at = now;
  } else if (action === 'assign') {
    const assigneeId = Number(payload.assignee_id);
    if (!Number.isInteger(assigneeId) || assigneeId < 1) return mockFailure('INVALID_ASSIGNEE', '请选择当前租户用户');
    incident.assignee = assigneeId;
    incident.assignee_name = assigneeId === 1 ? 'demo-operator' : `tenant-user-${assigneeId}`;
  } else if (action === 'resolve') {
    incident.status = 'resolved';
    incident.resolved_by = 1;
    incident.resolved_by_name = 'demo-operator';
    incident.resolved_at = now;
  }
  if (payload.note) incident.resolution_note = appendIncidentNote(incident, payload.note);
  incident.updated_at = now;
  return successResponse({ ...incident });
};

export const mockSyncAlertIncidentRetryPreview = (id) => {
  const preview = mockRetryPreviewByIncident[id] || {
    sync_job_id: null,
    source_sync_run_id: null,
    source_run_id: '',
    environment: 'unknown',
    execution_mode: 'simulation',
    external_api_called: false,
    allowed: false,
    blocked_reason: '同步事件不存在。',
    requires_confirmation: true
  };
  return successResponse({ incident_id: Number(id), ...preview, external_api_called: false });
};

export const mockSyncAlertIncidentRetry = (id, payload = {}) => {
  const preview = mockRetryPreviewByIncident[id];
  const key = String(payload.idempotency_key || '').trim();
  if (payload.confirmed !== true) return mockFailure('CONFIRMATION_REQUIRED', '必须明确确认重试');
  if (key.length < 8) return mockFailure('INVALID_IDEMPOTENCY_KEY', '幂等键至少需要 8 个字符');
  if (!preview || !preview.allowed) return mockFailure('RETRY_BLOCKED', preview?.blocked_reason || '同步事件不可重试');
  return successResponse({
    created: true,
    incident_id: Number(id),
    external_api_called: false,
    run: {
      id: 400 + Number(id),
      run_id: `MOCK-MANUAL-RETRY-${id}`,
      status: 'success',
      masked_error_message: ''
    }
  });
};

const mockAuthorizationRows = [{
  id: 201,
  integration_config_id: 1,
  store_id: 1,
  store_code: 'demo-store-sg',
  store_name: '新加坡示例店铺',
  platform: 'shopee',
  region: 'SG',
  status: 'active',
  platform_store_id: 'masked-external-store-001',
  scopes: ['shop.info', 'order.read'],
  credential_mask: { access_credential_hint: '••••0001', refresh_credential_hint: '••••0001' },
  expires_at: '2026-09-30T00:00:00Z',
  token_expires_at: '2026-09-30T00:00:00Z',
  last_error_code: '',
  masked_error_message: '',
  authorized_at: '2026-09-01T09:00:00Z',
  refreshed_at: '2026-09-01T10:00:00Z',
  revoked_at: null,
  created_at: '2026-09-01T09:00:00Z',
  updated_at: '2026-09-01T10:00:00Z'
}, {
  id: 203,
  integration_config_id: 1,
  store_id: 1,
  store_code: 'demo-store-sg',
  store_name: '新加坡示例店铺',
  platform: 'shopee',
  region: 'SG',
  status: 'expired',
  platform_store_id: 'masked-external-store-old',
  scopes: ['shop.info'],
  credential_mask: { access_credential_hint: '••••0203', refresh_credential_hint: '••••0203' },
  expires_at: '2026-08-01T00:00:00Z',
  token_expires_at: '2026-08-01T00:00:00Z',
  last_error_code: 'TOKEN_EXPIRED',
  masked_error_message: '授权令牌已到期，请重新授权。',
  refreshed_at: null,
  revoked_at: null,
  authorized_at: '2026-07-01T09:00:00Z',
  created_at: '2026-07-01T09:00:00Z',
  updated_at: '2026-08-01T00:00:00Z'
}, {
  id: 204,
  integration_config_id: 1,
  store_id: 1,
  store_code: 'demo-store-sg',
  store_name: '新加坡示例店铺',
  platform: 'shopee',
  region: 'SG',
  status: 'revoked',
  platform_store_id: 'masked-external-store-revoked',
  scopes: ['shop.info', 'order.read'],
  credential_mask: { access_credential_hint: '••••0204', refresh_credential_hint: '••••0204' },
  expires_at: '2026-07-15T00:00:00Z',
  token_expires_at: '2026-07-15T00:00:00Z',
  last_error_code: 'AUTHORIZATION_REVOKED',
  masked_error_message: '该授权已由平台或管理员撤销。',
  refreshed_at: null,
  revoked_at: '2026-07-20T03:00:00Z',
  authorized_at: '2026-06-15T09:00:00Z',
  created_at: '2026-06-15T09:00:00Z',
  updated_at: '2026-07-20T03:00:00Z'
}, {
  id: 205,
  integration_config_id: 1,
  store_id: 1,
  store_code: 'demo-store-sg',
  store_name: '新加坡示例店铺',
  platform: 'shopee',
  region: 'SG',
  status: 'error',
  platform_store_id: 'masked-external-store-error',
  scopes: ['shop.info', 'order.read'],
  credential_mask: { access_credential_hint: '••••0205', refresh_credential_hint: '••••0205' },
  expires_at: '2026-09-25T00:00:00Z',
  token_expires_at: '2026-09-25T00:00:00Z',
  last_error_code: 'PLATFORM_AUTH_ERROR',
  masked_error_message: '平台授权校验失败，凭据仍以掩码展示。',
  refreshed_at: null,
  revoked_at: null,
  authorized_at: '2026-08-25T09:00:00Z',
  created_at: '2026-08-25T09:00:00Z',
  updated_at: '2026-08-25T09:05:00Z'
}, {
  id: 206,
  integration_config_id: 1,
  store_id: 1,
  store_code: 'demo-store-sg',
  store_name: '新加坡示例店铺',
  platform: 'shopee',
  region: 'SG',
  status: 'pending',
  platform_store_id: 'masked-external-store-pending',
  scopes: ['shop.info'],
  credential_mask: { access_credential_hint: '••••0206', refresh_credential_hint: '••••0206' },
  expires_at: null,
  token_expires_at: null,
  last_error_code: '',
  masked_error_message: '等待平台授权回调完成。',
  refreshed_at: null,
  revoked_at: null,
  authorized_at: null,
  created_at: '2026-09-02T09:00:00Z',
  updated_at: '2026-09-02T09:00:00Z'
}];

// Explicit Mock OAuth keeps the same two-step contract as production while
// using only synthetic identifiers.  The short-lived state is retained in
// memory so a callback cannot be replayed or attached to another store.
const mockOAuthSessions = new Map();

const mockOAuthParam = (value) => Array.isArray(value) ? value[0] : value;

const mockOAuthState = (payload = {}) => {
  const platform = String(payload.platform || 'shopee').trim().toLowerCase();
  const storeId = String(payload.store_id || '');
  const configId = String(payload.integration_config_id || '');
  return `mock-oauth-state-${platform}-${storeId || 'store'}-${configId || 'config'}-${Date.now()}`;
};

export const mockStartStoreAuthorizationOAuth = (payload = {}) => {
  const platform = String(payload.platform || 'shopee').trim().toLowerCase();
  const state = mockOAuthState({ ...payload, platform });
  const storeId = payload.store_id ?? '';
  const configId = payload.integration_config_id ?? '';
  const existing = mockAuthorizationRows.find((row) => (
    String(row.store_id) === String(storeId)
    && String(row.integration_config_id) === String(configId)
    && row.platform === platform
  ));
  const shopId = existing?.platform_store_id || `mock-${platform}-store-${storeId || 'demo'}`;
  const simulationCallback = {
    state,
    code: `synthetic-${platform}-code`,
    shop_id: shopId,
    sign: `mock-signature-${state}`
  };
  mockOAuthSessions.set(state, {
    platform,
    store_id: storeId,
    integration_config_id: configId,
    region: payload.region || '',
    scopes: Array.isArray(payload.scopes) ? [...payload.scopes] : [],
    shop_id: shopId,
  });
  const authorizationUrl = `https://sandbox.example.invalid/oauth/authorize?state=${encodeURIComponent(state)}&store_id=${encodeURIComponent(storeId)}`;
  return successResponse({
    platform,
    state,
    expires_in: 600,
    authorization_url: authorizationUrl,
    // Kept for the existing platform-drill adapter; new callers use the
    // backend-compatible authorization_url field above.
    auth_url: authorizationUrl,
    simulation_callback: simulationCallback,
  });
};

export const mockCompleteSyntheticStoreAuthorization = (platform, params = {}) => {
  const normalizedPlatform = String(platform || '').trim().toLowerCase();
  const state = String(mockOAuthParam(params.state) || '');
  const session = mockOAuthSessions.get(state);
  if (!session || session.platform !== normalizedPlatform) {
    return mockFailure('MOCK_OAUTH_STATE_INVALID', '模拟授权状态无效或已完成');
  }
  const code = String(mockOAuthParam(params.code) || '');
  const shopId = String(mockOAuthParam(params.shop_id) || '');
  const signature = String(mockOAuthParam(params.sign) || '');
  if (!code || !shopId || signature !== `mock-signature-${state}`) {
    mockOAuthSessions.delete(state);
    return mockFailure('MOCK_OAUTH_CALLBACK_INVALID', '模拟授权回调参数校验失败');
  }

  mockOAuthSessions.delete(state);
  const existing = mockAuthorizationRows.find((row) => (
    String(row.store_id) === String(session.store_id)
    && String(row.integration_config_id) === String(session.integration_config_id)
    && row.platform === normalizedPlatform
  ));
  const now = new Date().toISOString();
  const authorization = existing || {
    id: Math.max(...mockAuthorizationRows.map((row) => row.id), 200) + 1,
    integration_config_id: Number(session.integration_config_id) || session.integration_config_id,
    store_id: Number(session.store_id) || session.store_id,
    store_code: `mock-store-${session.store_id || 'demo'}`,
    store_name: '模拟店铺',
    platform: normalizedPlatform,
    region: session.region,
    status: 'pending',
    platform_store_id: shopId,
    token_expires_at: null,
    refreshed_at: null,
    updated_at: now,
  };
  authorization.status = 'active';
  authorization.platform_store_id = shopId;
  authorization.updated_at = now;
  if (!existing) mockAuthorizationRows.push(authorization);
  return successResponse({
    simulation: true,
    external_api_called: false,
    platform: normalizedPlatform,
    store_authorization_id: authorization.id,
    authorization: { ...authorization },
  });
};

const mockWarehouseAuthorizationRows = [{
  id: 202,
  integration_config_id: 3,
  warehouse_id: 1,
  warehouse_code: 'MY-WMS-01',
  warehouse_name: '马来极风仓',
  country_code: 'MY',
  provider: 'jifeng_wms',
  status: 'active',
  scopes: ['inventory.read'],
  credential_mask: { credential_hint: '••••0202' },
  token_expires_at: '2026-12-31T00:00:00Z',
  authorized_at: '2026-09-01T09:00:00Z',
  last_verified_at: '2026-09-01T09:30:00Z',
  revoked_at: null,
  last_error_code: '',
  masked_error_message: ''
}, {
  id: 207,
  integration_config_id: 3,
  warehouse_id: 1,
  warehouse_code: 'MY-WMS-01',
  warehouse_name: '马来极风仓',
  country_code: 'MY',
  provider: 'jifeng_wms',
  status: 'expired',
  scopes: ['inventory.read'],
  credential_mask: { credential_hint: '••••0207' },
  token_expires_at: '2026-08-01T00:00:00Z',
  authorized_at: '2026-07-01T09:00:00Z',
  last_verified_at: '2026-07-31T09:30:00Z',
  revoked_at: null,
  last_error_code: 'TOKEN_EXPIRED',
  masked_error_message: '库存 API 令牌已到期。'
}, {
  id: 208,
  integration_config_id: 3,
  warehouse_id: 1,
  warehouse_code: 'MY-WMS-01',
  warehouse_name: '马来极风仓',
  country_code: 'MY',
  provider: 'jifeng_wms',
  status: 'revoked',
  scopes: ['inventory.read'],
  credential_mask: { credential_hint: '••••0208' },
  token_expires_at: '2026-08-15T00:00:00Z',
  authorized_at: '2026-06-15T09:00:00Z',
  last_verified_at: '2026-08-01T09:30:00Z',
  revoked_at: '2026-08-20T03:00:00Z',
  last_error_code: 'AUTHORIZATION_REVOKED',
  masked_error_message: '该库存 API 授权已解除。'
}, {
  id: 209,
  integration_config_id: 3,
  warehouse_id: 1,
  warehouse_code: 'MY-WMS-01',
  warehouse_name: '马来极风仓',
  country_code: 'MY',
  provider: 'jifeng_wms',
  status: 'error',
  scopes: ['inventory.read'],
  credential_mask: { credential_hint: '••••0209' },
  token_expires_at: '2026-10-01T00:00:00Z',
  authorized_at: '2026-08-25T09:00:00Z',
  last_verified_at: null,
  revoked_at: null,
  last_error_code: 'WMS_AUTH_ERROR',
  masked_error_message: '极风 WMS 授权校验失败。'
}, {
  id: 210,
  integration_config_id: 3,
  warehouse_id: 1,
  warehouse_code: 'MY-WMS-01',
  warehouse_name: '马来极风仓',
  country_code: 'MY',
  provider: 'jifeng_wms',
  status: 'pending',
  scopes: ['inventory.read'],
  credential_mask: { credential_hint: '••••0210' },
  token_expires_at: null,
  authorized_at: null,
  last_verified_at: null,
  revoked_at: null,
  last_error_code: '',
  masked_error_message: '等待库存 API 凭据维护完成。'
}];

const subjectApiConfig = (item) => ({
  id: item.id,
  platform: item.platform,
  api_type: item.api_type,
  account_alias: item.account_alias,
  environment: item.environment,
  status: item.status,
  regions: [...(item.regions || [])],
  callback_url: item.callback_url,
  scopes: [...(item.scopes || [])],
  oauth_ready: item.status !== 'disabled',
  oauth_blockers: []
});

const emptySubjectApiAccess = (subjectType, subjectId) => ({
  subject_type: subjectType,
  subject_id: subjectId,
  subject: null,
  api_types: [],
  configs: [],
  bindings: [],
  token_policy: 'platform-default'
});

// This mirrors subject_api_access() for the one store available in the local
// master-data mock. All identifiers are synthetic or masked metadata.
export const mockSubjectApiAccess = (subjectType = 'store', subjectId = 1) => {
  if (subjectType === 'warehouse') {
    const warehouseRows = mockWarehouseAuthorizationRows.filter((row) => String(row.warehouse_id) === String(subjectId));
    if (String(subjectId) !== '1') {
      return {
        success: false,
        code: 'MOCK_NOT_FOUND',
        message: '模拟数据未提供该仓库的 API 接入样例',
        data: emptySubjectApiAccess(subjectType, subjectId)
      };
    }
    return successResponse({
      subject_type: 'warehouse',
      subject: {
        id: 1,
        code: 'MY-WMS-01',
        name: '马来极风仓',
        country_code: 'MY',
        platform: 'jifeng_wms',
        platform_name: '马来极风',
        service_platform_id: 2,
        service_platform_type: 'warehouse_third_party'
      },
      api_types: ['inventory'],
      configs: configFixtures.filter((item) => item.platform === 'jifeng_wms').map(subjectApiConfig),
      bindings: warehouseRows.map((warehouse) => ({
        ...warehouse,
        api_type: 'inventory',
        account_alias: 'demo-wms',
        last_run_at: '2026-09-01T09:30:00Z',
        has_sync_job: Boolean(warehouseInventorySyncJob(warehouse.id, warehouse.integration_config_id)),
        sync_job_id: warehouseInventorySyncJob(warehouse.id, warehouse.integration_config_id)?.id || null,
      })),
      token_policy: 'auto-refresh'
    });
  }
  const isDemoStore = subjectType === 'store'
    && (subjectId === undefined || subjectId === null || String(subjectId) === '1' || String(subjectId) === 'demo-store-sg');
  if (!isDemoStore) {
    return {
      success: false,
      code: 'MOCK_NOT_FOUND',
      message: '模拟数据未提供该业务主体的 API 接入样例',
      data: emptySubjectApiAccess(subjectType, subjectId)
    };
  }

  const subjectBindings = mockAuthorizationRows
    .filter((row) => row.store_id === 1)
    .map((row) => ({
      id: row.id,
      api_type: 'marketplace',
      status: row.status,
      integration_config_id: row.integration_config_id,
      account_alias: configFixtures.find((item) => item.id === row.integration_config_id)?.account_alias || 'demo-shopee',
      platform_store_id: row.platform_store_id,
      scopes: [...(row.scopes || [])],
      expires_at: row.expires_at || row.token_expires_at || null,
      token_expires_at: row.token_expires_at || row.expires_at || null,
      credential_mask: row.credential_mask || {},
      authorized_at: row.authorized_at || null,
      last_verified_at: row.refreshed_at || null,
      last_run_at: storeAuthorizationSyncJob(row.id, row.integration_config_id)?.last_run_at || null,
      has_sync_job: Boolean(storeAuthorizationSyncJob(row.id, row.integration_config_id)),
      sync_job_id: storeAuthorizationSyncJob(row.id, row.integration_config_id)?.id || null,
      last_error_code: row.last_error_code || (row.status === 'active' ? '' : 'MOCK_AUTHORIZATION_REVOKED'),
      masked_error_message: row.masked_error_message || '',
      revoked_at: row.revoked_at || null,
      created_at: row.created_at || null,
      updated_at: row.updated_at || null,
    }));

  return successResponse({
    subject_type: 'store',
    subject: {
      id: 1,
      code: 'demo-store-sg',
      name: '新加坡示例店铺',
      country_code: 'SG',
      platform: 'shopee',
      platform_name: 'Shopee'
    },
    api_types: ['marketplace', 'advertising'],
    configs: configFixtures
      .filter((item) => item.platform === 'shopee' && (item.regions || []).includes('SG'))
      .map(subjectApiConfig),
    bindings: subjectBindings,
    token_policy: 'auto-refresh'
  });
};

export const mockWarehouseAuthorizations = (params = {}) => {
  const results = mockWarehouseAuthorizationRows.filter((row) => (
    (!params.warehouse_id || String(row.warehouse_id) === String(params.warehouse_id))
    && (!params.integration_config_id || String(row.integration_config_id) === String(params.integration_config_id))
    && (!params.status || row.status === params.status)
  ));
  return successResponse({ count: results.length, results: results.map((row) => ({ ...row })) });
};

export const mockBindWarehouseAuthorization = (payload = {}) => {
  const current = mockWarehouseAuthorizationRows.find((row) => (
    String(row.warehouse_id) === String(payload.warehouse_id) && row.status === 'active'
  ));
  if (current && String(current.integration_config_id) === String(payload.integration_config_id)) {
    return successResponse({ idempotent: true, operation: 'already_bound', authorization: { ...current } });
  }
  if (current && !payload.replace) return mockFailure('STATE_CONFLICT', '仓库已有库存 API 绑定，请明确确认后再更换绑定');
  if (current) {
    current.status = 'revoked';
    current.revoked_at = new Date().toISOString();
  }
  const config = configFixtures.find((item) => String(item.id) === String(payload.integration_config_id));
  if (!config || config.platform !== 'jifeng_wms') return mockFailure('INVALID_CONFIG', '请选择库存 API 配置');
  const record = {
    id: Math.max(...mockWarehouseAuthorizationRows.map((item) => item.id), 202) + 1,
    integration_config_id: config.id,
    warehouse_id: Number(payload.warehouse_id),
    warehouse_code: 'MY-WMS-01',
    warehouse_name: '马来极风仓',
    country_code: 'MY',
    provider: 'jifeng_wms',
    status: 'active',
    authorized_at: new Date().toISOString(),
    last_verified_at: null,
    revoked_at: null,
    last_error_code: ''
  };
  mockWarehouseAuthorizationRows.push(record);
  return successResponse({ idempotent: false, operation: payload.replace ? 'warehouse_rebind' : 'warehouse_authorize', authorization: { ...record } });
};

export const mockRevokeWarehouseAuthorization = (id) => {
  const row = mockWarehouseAuthorizationRows.find((item) => String(item.id) === String(id));
  if (!row) return mockFailure('NOT_FOUND', '仓库 API 授权不存在');
  const idempotent = row.status === 'revoked';
  row.status = 'revoked';
  row.revoked_at = row.revoked_at || new Date().toISOString();
  return successResponse({ idempotent, authorization: { ...row } });
};

const warehouseInventorySyncJob = (authorizationId, configId) => workspaceJobs.find((job) => {
  const jobAuthorizationId = job.warehouse_authorization_id ?? job.selected_authorization_id;
  if (String(jobAuthorizationId) !== String(authorizationId)) return false;
  if (job.resource_type !== 'inventory_snapshot') return false;
  if (configId && job.integration_config_id && String(job.integration_config_id) !== String(configId)) return false;
  return true;
});

const storeAuthorizationSyncJob = (authorizationId, configId) => workspaceJobs.find((job) => {
  const jobAuthorizationId = job.store_authorization_id ?? job.selected_authorization_id;
  if (String(jobAuthorizationId) !== String(authorizationId)) return false;
  if (job.subject_type !== 'store' || job.resource_type === 'inventory_snapshot') return false;
  if (String(job.integration_config_id || '') !== String(configId)) return false;
  return true;
});

// Unlike mockIntegrationConfigDetail(), this fixture models the readonly
// operation contract: it validates the selected warehouse authorization and
// its inventory snapshot task, then explicitly reports a non-network check.
export const mockCheckIntegrationReadonlyConnection = (id, payload = {}) => {
  const config = configFixtures.find((item) => String(item.id) === String(id));
  if (!config) return mockFailure('CONFIG_NOT_FOUND', '接入配置不存在，无法执行只读检查');

  const storeAuthorizationId = payload?.store_authorization_id;
  if (storeAuthorizationId !== undefined && storeAuthorizationId !== null && storeAuthorizationId !== '') {
    const authorization = mockAuthorizationRows.find((row) => (
      String(row.id) === String(storeAuthorizationId)
      && row.status === 'active'
      && String(row.integration_config_id) === String(config.id)
      && row.platform === config.platform
    ));
    if (!authorization) return mockFailure('INVALID_STORE_AUTHORIZATION', '当前店铺授权与接入配置不匹配或已撤销');
    const job = storeAuthorizationSyncJob(authorization.id, config.id);
    if (!job) return mockFailure('SYNC_JOB_REQUIRED', '请先创建当前店铺授权对应的同步任务，再执行只读检查');
    return successResponse({
      simulated: true,
      external_api_called: false,
      token_refreshed: false,
      resource_type: job.resource_type,
      store_authorization_id: authorization.id,
      sync_job_id: job.id,
      checked_at: new Date().toISOString(),
    });
  }

  const warehouseAuthorizationId = payload?.warehouse_authorization_id;
  if (warehouseAuthorizationId !== undefined && warehouseAuthorizationId !== null && warehouseAuthorizationId !== '') {
    const authorization = mockWarehouseAuthorizationRows.find((row) => (
      String(row.id) === String(warehouseAuthorizationId)
      && row.status === 'active'
      && String(row.integration_config_id) === String(config.id)
    ));
    if (!authorization) return mockFailure('INVALID_WAREHOUSE_AUTHORIZATION', '当前仓库 API 授权与接入配置不匹配或已解除');
    const job = warehouseInventorySyncJob(authorization.id, config.id);
    if (!job) return mockFailure('SYNC_JOB_REQUIRED', '请先创建库存同步任务，再执行只读检查');
    return successResponse({
      simulated: true,
      external_api_called: false,
      token_refreshed: false,
      resource_type: 'inventory_snapshot',
      warehouse_authorization_id: authorization.id,
      sync_job_id: job.id,
      checked_at: new Date().toISOString(),
    });
  }

  const job = workspaceJobs.find((candidate) => candidate.platform === config.platform);
  if (!job) return mockFailure('SYNC_JOB_REQUIRED', '当前配置没有可用于只读检查的同步任务');
  return successResponse({
    simulated: true,
    external_api_called: false,
    token_refreshed: false,
    resource_type: job.resource_type,
    sync_job_id: job.id,
    checked_at: new Date().toISOString(),
  });
};

export const mockStoreAuthorizations = (params = {}) => {
  const results = mockAuthorizationRows.filter((row) => (
    (!params.platform || row.platform === params.platform)
    && (!params.status || row.status === params.status)
    && (!params.store_id || String(row.store_id) === String(params.store_id))
  ));
  return successResponse({ count: results.length, results: results.map((row) => ({ ...row })) });
};

export const mockStoreAuthorizationDetail = (id) => {
  const row = mockAuthorizationRows.find((item) => String(item.id) === String(id));
  return row ? successResponse({ ...row }) : mockFailure('NOT_FOUND', '店铺授权不存在');
};

export const mockRefreshStoreAuthorization = (id) => {
  const row = mockAuthorizationRows.find((item) => String(item.id) === String(id));
  if (!row) return mockFailure('NOT_FOUND', '店铺授权不存在');
  row.status = 'active';
  row.token_expires_at = '2026-10-30T00:00:00Z';
  return successResponse({ ...row });
};

export const mockRevokeStoreAuthorization = (id) => {
  const row = mockAuthorizationRows.find((item) => String(item.id) === String(id));
  if (!row) return mockFailure('NOT_FOUND', '店铺授权不存在');
  const idempotent = row.status === 'revoked';
  row.status = 'revoked';
  return successResponse({ idempotent, authorization: { ...row } });
};

export const mockConnectionCapabilities = () => successResponse({
  authorization_id: 201,
  available_codes: ['PRODUCT', 'CATEGORY', 'LISTING', 'PRICE', 'ORDER', 'INVENTORY', 'FULFILLMENT', 'WAREHOUSE', 'RETURN_REFUND', 'SETTLEMENT', 'PAYMENT', 'ADVERTISING', 'AFFILIATE', 'REVIEW', 'REPORT', 'WEBHOOK'],
  results: [
    { capability_code: 'ORDER', read_enabled: true, write_enabled: false, sync_mode: 'scheduled', source_priority: 10, status: 'active' },
    { capability_code: 'RETURN_REFUND', read_enabled: true, write_enabled: false, sync_mode: 'manual', source_priority: 20, status: 'active' }
  ]
});
