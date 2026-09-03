import { requestWithMockFallback } from './request';
import {
  mockApiSyncLogs,
  mockApiSyncTasks,
  mockIntegrationConfigDetail,
  mockIntegrationConfigs,
  mockSyncJobs,
  mockCreateSyncJob,
  mockSyncRunDetail,
  mockSyncRuns,
  mockIntegrationWorkspace,
  mockSyncAlertIncidents,
  mockSyncAlertIncidentAction,
  mockSyncAlertIncidentRetryPreview,
  mockSyncAlertIncidentRetry,
  mockStoreAuthorizations,
  mockStoreAuthorizationDetail,
  mockSubjectApiAccess,
  mockRefreshStoreAuthorization,
  mockRevokeStoreAuthorization,
  mockStartStoreAuthorizationOAuth,
  mockConnectionCapabilities
} from '../mock/integrations';
import {
  mockProductionIntegrationSettings,
  mockCreateProductionIntegrationSettingsVersion,
  mockApproveProductionIntegrationSettingsVersion,
  mockRollbackProductionIntegrationSettingsVersion
} from '../mock/productionSettings';

// These fixtures keep the new operational pages useful in the local mock
// environment while preserving the production API contract.  They contain
// only identifiers and redacted metadata; no platform credential is ever
// embedded in the frontend bundle.
const mockStoreMappingRows = [
  {
    id: 301,
    tenant_id: 'mock-tenant-001',
    platform: 'shopee',
    store_id: 1,
    store_code: 'demo-store-sg',
    store_name: '新加坡示例店铺',
    authorization_id: 201,
    platform_store_id: 'masked-external-store-001',
    region: 'SG',
    timezone: 'Asia/Singapore',
    currency: 'SGD',
    status: 'active',
    mapping_source: 'oauth_callback',
    mapped_by_id: 1,
    mapped_at: '2026-09-01T09:00:00Z',
    last_verified_at: '2026-09-01T09:00:00Z',
    created_at: '2026-09-01T09:00:00Z',
    updated_at: '2026-09-01T09:00:00Z'
  }
];

const mockProductMappingRows = [
  {
    id: 401,
    tenant_id: 'mock-tenant-001',
    platform: 'shopee',
    store_mapping_id: 301,
    platform_product_id: 'masked-product-001',
    platform_variant_id: 'masked-variant-001',
    platform_sku: 'DEMO-SKU-001',
    product_id: 1,
    sku_id: 11,
    sku_code: 'SKU-DEMO-001',
    status: 'suggested',
    mapping_source: 'suggested',
    confidence: 92,
    manually_confirmed: false,
    result_code: 'candidate_match',
    first_seen_at: '2026-09-01T09:10:00Z',
    last_verified_at: null,
    created_at: '2026-09-01T09:10:00Z',
    updated_at: '2026-09-01T09:10:00Z'
  }
];

const mockIntegrationAuditRows = [
  {
    id: 501,
    tenant_id: 'mock-tenant-001',
    integration_config_id: 1,
    platform: 'shopee',
    environment: 'sandbox',
    action: 'oauth_start',
    actor_id: 1,
    result: 'success',
    masked_detail: { platform: 'shopee', region: 'SG', store_id: 1 },
    created_at: '2026-09-01T09:00:00Z'
  }
];

const mockCollectionResponse = (rows) => ({
  success: true,
  code: 'OK',
  message: 'mock',
  data: { count: rows.length, results: rows.map((row) => ({ ...row })) }
});

const mockWriteResponse = (payload, id = null) => ({
  success: true,
  code: 'OK',
  message: 'Mock操作已记录',
  data: { ...(id == null ? {} : { id }), ...payload, api_status: 'mock' }
});

export const fetchIntegrationConfigs = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/configs/' },
    mockIntegrationConfigs,
    'integrations.configs'
  );

export const fetchPlatformIntegrationReadiness = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/readiness/' },
    () => ({
      success: false,
      code: 'READINESS_UNAVAILABLE',
      message: '未能读取真实平台接入准备度，请检查后端服务。',
      data: null
    }),
    'integrations.readiness'
  );

// System-level production gates are deliberately separate from tenant
// integration configs.  The API returns only effective/read-only metadata;
// secrets remain in the custody service and are never sent to this client.
export const fetchProductionIntegrationSettings = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/production-settings/' },
    mockProductionIntegrationSettings,
    'integrations.production_settings'
  );

export const createProductionIntegrationSettingsVersion = (payload = {}) =>
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/integrations/production-settings/versions/', data: payload },
    () => mockCreateProductionIntegrationSettingsVersion(payload),
    'integrations.production_settings.create'
  );

export const approveProductionIntegrationSettingsVersion = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/production-settings/versions/${id}/approve/` },
    () => mockApproveProductionIntegrationSettingsVersion(id),
    'integrations.production_settings.approve'
  );

export const rollbackProductionIntegrationSettingsVersion = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/production-settings/versions/${id}/rollback/` },
    () => mockRollbackProductionIntegrationSettingsVersion(id),
    'integrations.production_settings.rollback'
  );

// Short aliases keep the API discoverable for settings-page adapters while
// retaining the explicit integration-oriented names above.
export const fetchProductionSettings = fetchProductionIntegrationSettings;
export const createProductionSettingsVersion = createProductionIntegrationSettingsVersion;
export const approveProductionSettingsVersion = approveProductionIntegrationSettingsVersion;
export const rollbackProductionSettingsVersion = rollbackProductionIntegrationSettingsVersion;

export const repairPlatformIntegrationContract = (id, payload) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/readiness/configs/${id}/repair-contract/`, data: payload },
    () => ({ success: false, code: 'MOCK_UNAVAILABLE', message: '模拟模式不修改生产接入配置。', data: null }),
    'integrations.readiness.repair_contract'
  );

export const setPlatformIntegrationReadonlyApproval = (id, payload) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/readiness/configs/${id}/readonly-approval/`, data: payload },
    () => ({ success: false, code: 'MOCK_UNAVAILABLE', message: '模拟模式不执行生产只读审批。', data: null }),
    'integrations.readiness.readonly_approval'
  );

export const fetchIntegrationConfigDetail = (id = 1) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/integrations/configs/${id}/` },
    () => mockIntegrationConfigDetail(id),
    'integrations.configs.detail'
  );

// Subject-scoped access is used by the master-data pages to show the
// currently bound API capabilities and to keep authorization in the same
// guarded integration workflow as the configuration pages.
export const fetchSubjectApiAccess = (subjectType, subjectId) =>
  requestWithMockFallback(
    {
      method: 'get',
      url: '/api/internal/integrations/subject-api-access/',
      params: { subject_type: subjectType, subject_id: subjectId }
    },
    () => mockSubjectApiAccess(subjectType, subjectId),
    'integrations.subject_api_access'
  );

export const startStoreAuthorization = (payload) =>
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/integrations/store-authorizations/oauth/start/', data: payload },
    () => ({ success: false, code: 'MOCK_UNAVAILABLE', message: '模拟模式不发起平台授权', data: null }),
    'integrations.store_authorizations.oauth_start'
  );

export const completeSyntheticStoreAuthorization = (platform, params) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/integrations/store-authorizations/oauth/callback/${platform}/`, params },
    () => ({ success: false, code: 'MOCK_UNAVAILABLE', message: '模拟授权回调不可用', data: null }),
    'integrations.store_authorizations.oauth_callback'
  );

export const createIntegrationConfig = (payload) =>
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/integrations/workspace-configs/', data: payload },
    mockIntegrationConfigDetail,
    'integrations.configs.create'
  );

export const rotateIntegrationSecretValues = (id, payload, idempotencyKey) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: `/api/internal/integrations/configs/${id}/credentials/rotate/`,
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey }
    },
    mockIntegrationConfigDetail,
    'integrations.configs.credentials.rotate'
  );

export const checkIntegrationReference = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/reference-check/`, data: {} },
    mockIntegrationConfigDetail,
    'integrations.configs.reference_check'
  );

export const checkIntegrationConsistency = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/consistency-check/`, data: {} },
    mockIntegrationConfigDetail,
    'integrations.configs.consistency_check'
  );

export const checkIntegrationReadonlyConnection = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/readonly-check/`, data: {} },
    mockIntegrationConfigDetail,
    'integrations.configs.readonly_check'
  );

export const updateIntegrationConfig = (id, payload) =>
  requestWithMockFallback(
    { method: 'patch', url: `/api/internal/integrations/configs/${id}/`, data: payload },
    () => mockIntegrationConfigDetail(id),
    'integrations.configs.update'
  );

export const disableIntegrationConfig = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/disable/`, data: {} },
    () => mockIntegrationConfigDetail(id),
    'integrations.configs.disable'
  );

export const deleteIntegrationConfig = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/delete/`, data: {} },
    () => ({ success: true, code: 'OK', message: 'deleted', data: { id, deleted: true } }),
    'integrations.configs.delete'
  );

export const verifyIntegrationConfig = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/verify/`, data: {} },
    () => mockIntegrationConfigDetail(id),
    'integrations.configs.verify'
  );

export const fetchIntegrationWorkspace = (mode = 'sync-jobs', params = {}) => {
  const workspaceParams = { ...params, mode, page: 1, page_size: 100 };
  return requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/workspace/', params: workspaceParams },
    () => mockIntegrationWorkspace(mode, workspaceParams),
    `integrations.workspace.${mode}`
  );
};

export const fetchSyncJobs = (params = {}) => fetchIntegrationWorkspace('sync-jobs', params);

export const createSyncJob = (payload) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/integrations/sync-jobs/', data: payload },
  () => mockCreateSyncJob(payload),
  'integrations.sync_jobs.create'
);

export const fetchSyncAlertIncidents = (filters = {}) => {
  const params = typeof filters === 'string' ? { status: filters } : { ...(filters || {}) };
  return requestWithMockFallback(
    {
      method: 'get',
      url: '/api/internal/integrations/sync-alert-incidents/',
      params: { status: params.status || '' }
    },
    () => mockSyncAlertIncidents(params.status || ''),
    'integrations.sync_alert_incidents'
  );
};

export const actOnSyncAlertIncident = (id, payload) => requestWithMockFallback(
  {
    method: 'post',
    url: `/api/internal/integrations/sync-alert-incidents/${id}/action/`,
    data: payload
  },
  () => mockSyncAlertIncidentAction(id, payload),
  'integrations.sync_alert_incidents.action'
);

export const fetchSyncAlertIncidentRetryPreview = (id) => requestWithMockFallback(
  {
    method: 'get',
    url: `/api/internal/integrations/sync-alert-incidents/${id}/retry/`
  },
  () => mockSyncAlertIncidentRetryPreview(id),
  'integrations.sync_alert_incidents.retry_preview'
);

export const retrySyncAlertIncident = (id, idempotencyKey) => requestWithMockFallback(
  {
    method: 'post',
    url: `/api/internal/integrations/sync-alert-incidents/${id}/retry/`,
    data: { confirmed: true, idempotency_key: idempotencyKey }
  },
  () => mockSyncAlertIncidentRetry(id, { confirmed: true, idempotency_key: idempotencyKey }),
  'integrations.sync_alert_incidents.retry'
);

// Compatibility aliases keep the incident API discoverable to callers that
// use update/retry naming while preserving one endpoint implementation.
export const updateSyncAlertIncident = actOnSyncAlertIncident;
export const fetchSyncAlertRetryPreview = fetchSyncAlertIncidentRetryPreview;
export const retrySyncAlert = retrySyncAlertIncident;

export const fetchSyncRuns = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-runs/' },
    mockSyncRuns,
    'integrations.sync_runs'
  );

export const fetchSyncRunDetail = (id = 1) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/integrations/sync-runs/${id}/` },
    mockSyncRunDetail,
    'integrations.sync_runs.detail'
  );

export const runSyncJobMock = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/sync-jobs/${id}/run-mock/` },
    mockSyncRunDetail,
    'integrations.sync_jobs.run_mock'
  );

export const disableSyncJob = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/sync-jobs/${id}/disable/` },
    mockSyncJobs,
    'integrations.sync_jobs.disable'
  );

export const runSyncJob = (id, idempotencyKey) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: `/api/internal/integrations/sync-jobs/${id}/run/`,
      data: idempotencyKey ? { idempotency_key: idempotencyKey } : {}
    },
    mockSyncRunDetail,
    'integrations.sync_jobs.run'
  );

export const updateSyncJob = (id, payload) =>
  requestWithMockFallback(
    { method: 'patch', url: `/api/internal/integrations/sync-jobs/${id}/`, data: payload },
    mockSyncJobs,
    'integrations.sync_jobs.update'
  );

export const toggleSyncJob = (id, enabled) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/sync-jobs/${id}/toggle/`, data: { enabled } },
    mockSyncJobs,
    'integrations.sync_jobs.toggle'
  );

export const previewSyncJobDelete = (id) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/integrations/sync-jobs/${id}/delete/` },
    () => ({ success: true, code: 'OK', message: 'preview', data: { can_delete: false, blockers: [] } }),
    'integrations.sync_jobs.delete_preview'
  );

export const deleteSyncJob = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/sync-jobs/${id}/delete/`, data: {} },
    mockSyncJobs,
    'integrations.sync_jobs.delete'
  );

export const retrySyncRun = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/sync-runs/${id}/retry/`, data: {} },
    mockSyncRunDetail,
    'integrations.sync_runs.retry'
  );

export const fetchApiSyncTasks = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-jobs/' },
    mockApiSyncTasks,
    'integrations.sync_jobs'
  );

export const fetchApiSyncLogs = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-runs/' },
    mockApiSyncLogs,
    'integrations.sync_runs'
  );

export const fetchStoreAuthorizations = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/store-authorizations/', params },
  () => mockStoreAuthorizations(params),
  'integrations.store_authorizations'
);

export const fetchStoreAuthorizationDetail = (authorizationId) => requestWithMockFallback(
  {
    method: 'get',
    url: `/api/internal/integrations/store-authorizations/${authorizationId}/`
  },
  () => mockStoreAuthorizationDetail(authorizationId),
  'integrations.store_authorizations.detail'
);

export const refreshStoreAuthorization = (authorizationId, payload = {}) => requestWithMockFallback(
  {
    method: 'post',
    url: `/api/internal/integrations/store-authorizations/${authorizationId}/refresh/`,
    data: payload
  },
  () => mockRefreshStoreAuthorization(authorizationId, payload),
  'integrations.store_authorizations.refresh'
);

export const revokeStoreAuthorization = (authorizationId) => requestWithMockFallback(
  {
    method: 'post',
    url: `/api/internal/integrations/store-authorizations/${authorizationId}/revoke/`,
    data: {}
  },
  () => mockRevokeStoreAuthorization(authorizationId),
  'integrations.store_authorizations.revoke'
);

export const startStoreAuthorizationOAuth = (payload = {}) => requestWithMockFallback(
  {
    method: 'post',
    url: '/api/internal/integrations/store-authorizations/oauth/start/',
    data: payload
  },
  () => mockStartStoreAuthorizationOAuth(payload),
  'integrations.store_authorizations.oauth_start'
);

// Keep the provider-oriented alias available to callers using the backend name.
export const startMarketplaceStoreOAuth = startStoreAuthorizationOAuth;

export const fetchConnectionCapabilities = (authorizationId) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/integrations/store-authorizations/${authorizationId}/capabilities/` },
  () => mockConnectionCapabilities(authorizationId),
  'integrations.connection_capabilities'
);

export const updateConnectionCapabilities = (authorizationId, capabilities) => requestWithMockFallback(
  { method: 'put', url: `/api/internal/integrations/store-authorizations/${authorizationId}/capabilities/`, data: { capabilities } },
  () => mockConnectionCapabilities(authorizationId, capabilities),
  'integrations.connection_capabilities.update'
);

export const fetchStoreMappings = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/store-mappings/', params },
  () => mockCollectionResponse(mockStoreMappingRows),
  'integrations.store_mappings'
);

export const fetchStoreMappingDetail = (mappingId) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/integrations/store-mappings/${mappingId}/` },
  () => {
    const row = mockStoreMappingRows.find((item) => String(item.id) === String(mappingId));
    return row ? mockWriteResponse(row, row.id) : { success: false, code: 'NOT_FOUND', message: '店铺映射不存在', data: null };
  },
  'integrations.store_mappings.detail'
);

export const createStoreMapping = (payload = {}) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/integrations/store-mappings/', data: payload },
  () => mockWriteResponse(payload, Math.max(...mockStoreMappingRows.map((item) => item.id), 300) + 1),
  'integrations.store_mappings.create'
);

export const updateStoreMapping = (mappingId, payload = {}) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/integrations/store-mappings/${mappingId}/`, data: payload },
  () => mockWriteResponse(payload, mappingId),
  'integrations.store_mappings.update'
);

export const fetchProductMappings = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/product-mappings/', params },
  () => mockCollectionResponse(mockProductMappingRows),
  'integrations.product_mappings'
);

export const fetchProductMappingDetail = (mappingId) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/integrations/product-mappings/${mappingId}/` },
  () => {
    const row = mockProductMappingRows.find((item) => String(item.id) === String(mappingId));
    return row ? mockWriteResponse(row, row.id) : { success: false, code: 'NOT_FOUND', message: '商品映射不存在', data: null };
  },
  'integrations.product_mappings.detail'
);

export const createProductMapping = (payload = {}) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/integrations/product-mappings/', data: payload },
  () => mockWriteResponse(payload, Math.max(...mockProductMappingRows.map((item) => item.id), 400) + 1),
  'integrations.product_mappings.create'
);

export const updateProductMapping = (mappingId, payload = {}) => requestWithMockFallback(
  { method: 'patch', url: `/api/internal/integrations/product-mappings/${mappingId}/`, data: payload },
  () => mockWriteResponse(payload, mappingId),
  'integrations.product_mappings.update'
);

export const confirmProductMapping = (mappingId, payload = {}) => updateProductMapping(
  mappingId,
  { ...payload, manually_confirmed: true }
);

// An unmapped product may only be registered as a suggestion first. Keeping
// this helper separate from confirmation makes the two backend state
// transitions explicit and prevents an accidental direct unmapped -> mapped
// action from the UI.
export const suggestProductMapping = (mappingId, payload = {}) => updateProductMapping(
  mappingId,
  { ...payload, manually_confirmed: false }
);

export const deactivateProductMapping = (mappingId) => updateProductMapping(
  mappingId,
  { status: 'inactive' }
);

export const fetchIntegrationAudit = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/audit/', params },
  () => mockCollectionResponse(mockIntegrationAuditRows),
  'integrations.audit'
);

// Keep the backend's collection naming discoverable to consumers that use
// "list" terminology in page adapters.
export const fetchIntegrationAuditLogs = fetchIntegrationAudit;

export const fetchMarketplaceStoreMappings = fetchStoreMappings;
export const createMarketplaceStoreMapping = createStoreMapping;
export const updateMarketplaceStoreMapping = updateStoreMapping;
export const fetchMarketplaceProductMappings = fetchProductMappings;
export const createMarketplaceProductMapping = createProductMapping;
export const updateMarketplaceProductMapping = updateProductMapping;
