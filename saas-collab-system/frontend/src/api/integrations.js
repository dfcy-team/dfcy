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
  mockRefreshStoreAuthorization,
  mockRevokeStoreAuthorization,
  mockStartStoreAuthorizationOAuth,
  mockConnectionCapabilities
} from '../mock/integrations';

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

export const fetchSyncAlertIncidents = (status = '') => requestWithMockFallback(
  {
    method: 'get',
    url: '/api/internal/integrations/sync-alert-incidents/',
    params: { status: status || '' }
  },
  () => mockSyncAlertIncidents(status),
  'integrations.sync_alert_incidents'
);

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
