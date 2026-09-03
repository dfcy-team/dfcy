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

const configFixtures = [config, shopeeSandboxConfig];

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
    subject_code: 'demo-wh-cn',
    subject_name: '华南示例仓',
    region: 'CN',
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

export const mockIntegrationWorkspace = (mode = 'sync-jobs') => {
  const results = mode === 'configs'
    ? configFixtures
    : mode === 'sync-runs'
      ? workspaceRuns
      : workspaceJobs;
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
    pagination: { page: 1, page_size: 100, total: results.length, page_count: 1 },
    results: results.map((row) => ({ ...row }))
  });
};

export const mockCreateSyncJob = (payload = {}) => {
  const authorization = mockAuthorizationRows?.find?.((item) => String(item.id) === String(payload.store_authorization_id));
  if (!authorization) return mockFailure('INVALID_AUTHORIZATION', '请选择当前配置的店铺授权');
  if (workspaceJobs.some((item) => String(item.selected_authorization_id) === String(authorization.id) && item.resource_type === payload.resource_type)) {
    return mockFailure('DUPLICATE_SYNC_JOB', '该授权和资源已经存在同步任务');
  }
  const row = {
    id: Math.max(...workspaceJobs.map((item) => item.id), 0) + 1,
    integration_config_id: payload.integration_config_id,
    platform: authorization.platform,
    account_alias: 'demo-shopee',
    resource_type: payload.resource_type,
    schedule_type: payload.schedule_type || 'manual',
    execution_mode: 'simulation',
    status: 'disabled',
    is_enabled: false,
    health_state: 'disabled',
    schedule_state: 'disabled',
    blocked_reason: '任务创建后默认停用，请复核后在任务工作台启用',
    capability_state: 'ready',
    selected_authorization_id: authorization.id,
    subject_name: authorization.store_name,
    region: authorization.region,
  };
  workspaceJobs.push(row);
  return successResponse({ ...row, store_authorization_id: authorization.id });
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

export const mockSyncAlertIncidents = (status = '') => {
  const rows = status
    ? mockIncidentRows.filter((item) => item.status === status)
    : mockIncidentRows;
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
  token_expires_at: '2026-09-30T00:00:00Z',
  refreshed_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z'
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
      authorized_at: '2026-09-01T09:00:00Z',
      last_verified_at: row.refreshed_at || null,
      last_run_at: '2026-09-01T10:00:00Z',
      last_error_code: row.status === 'active' ? '' : 'MOCK_AUTHORIZATION_REVOKED'
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

export const mockStartStoreAuthorizationOAuth = (payload = {}) => successResponse({
  state: 'mock-oauth-state',
  platform: payload.platform || 'shopee',
  expires_in: 600,
  auth_url: `https://sandbox.example.invalid/oauth/authorize?state=mock-oauth-state&store_id=${encodeURIComponent(payload.store_id || '')}`
});

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
