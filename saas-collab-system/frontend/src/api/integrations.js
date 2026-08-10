import { createIdempotencyKey, requestApi, requestWithMockFallback, useMock } from './request';
import {
  mockApiSyncLogs,
  mockApiSyncTasks,
  mockIntegrationAudit,
  mockIntegrationConfigDetail,
  mockIntegrationConfigs,
  mockIntegrationConfigSchema,
  mockMarketplaceAuthorizationStart,
  mockMarketplaceStoreAuthorizations,
  mockSyncJobs,
  mockSyncRunDetail,
  mockSyncRuns
} from '../mock/integrations';

const configRequest = (config, mockHandler, moduleName) => (
  useMock ? requestWithMockFallback(config, mockHandler, moduleName) : requestApi(config)
);

export const fetchIntegrationConfigs = (params = {}) =>
  configRequest(
    { method: 'get', url: '/api/internal/integrations/configs/', params },
    mockIntegrationConfigs,
    'integrations.configs'
  );

export const fetchIntegrationConfigSchema = (platform, environment = 'sandbox') =>
  configRequest(
    { method: 'get', url: `/api/internal/integrations/platform-schemas/${platform}/`, params: { environment } },
    () => mockIntegrationConfigSchema(platform, environment),
    'integrations.configs.schema'
  );

export const fetchIntegrationConfigDetail = (id = 1) =>
  configRequest(
    { method: 'get', url: `/api/internal/integrations/configs/${id}/` },
    mockIntegrationConfigDetail,
    'integrations.configs.detail'
  );

export const createIntegrationConfig = (payload) =>
  configRequest(
    { method: 'post', url: '/api/internal/integrations/configs/', data: payload },
    mockIntegrationConfigDetail,
    'integrations.configs.create'
  );

export const updateIntegrationConfig = (id, payload) =>
  configRequest(
    { method: 'patch', url: `/api/internal/integrations/configs/${id}/`, data: payload },
    mockIntegrationConfigDetail,
    'integrations.configs.update'
  );

export const rotateIntegrationCredentials = (id, payload) =>
  configRequest(
    {
      method: 'post',
      url: `/api/internal/integrations/configs/${id}/credentials/rotate/`,
      data: payload,
      headers: { 'Idempotency-Key': createIdempotencyKey('credential-rotate') }
    },
    mockIntegrationConfigDetail,
    'integrations.configs.credentials.rotate'
  );

export const clearIntegrationCredentials = (id, payload) =>
  configRequest(
    {
      method: 'post',
      url: `/api/internal/integrations/configs/${id}/credentials/clear/`,
      data: payload,
      headers: { 'Idempotency-Key': createIdempotencyKey('credential-clear') }
    },
    mockIntegrationConfigDetail,
    'integrations.configs.credentials.clear'
  );

export const fetchIntegrationAudit = (id) =>
  configRequest(
    { method: 'get', url: `/api/internal/integrations/configs/${id}/audit/` },
    mockIntegrationAudit,
    'integrations.configs.audit'
  );

export const disableIntegrationConfig = (id) =>
  configRequest(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/disable/`, data: {} },
    mockIntegrationConfigDetail,
    'integrations.configs.disable'
  );

export const verifyIntegrationConfig = (id) =>
  configRequest(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/verify/`, data: {} },
    mockIntegrationConfigDetail,
    'integrations.configs.verify'
  );

export const fetchMarketplaceStoreAuthorizations = (params = {}) =>
  configRequest(
    { method: 'get', url: '/api/internal/integrations/store-authorizations/', params },
    mockMarketplaceStoreAuthorizations,
    'integrations.store_authorizations'
  );

export const startMarketplaceStoreAuthorization = (payload) =>
  configRequest(
    { method: 'post', url: '/api/internal/integrations/store-authorizations/oauth/start/', data: payload },
    mockMarketplaceAuthorizationStart,
    'integrations.store_authorizations.oauth_start'
  );

export const refreshMarketplaceStoreAuthorization = (id) =>
  configRequest(
    { method: 'post', url: `/api/internal/integrations/store-authorizations/${id}/refresh/`, data: {} },
    mockMarketplaceStoreAuthorizations,
    'integrations.store_authorizations.refresh'
  );

export const revokeMarketplaceStoreAuthorization = (id) =>
  configRequest(
    { method: 'post', url: `/api/internal/integrations/store-authorizations/${id}/revoke/`, data: {} },
    mockMarketplaceStoreAuthorizations,
    'integrations.store_authorizations.revoke'
  );

export const fetchSyncJobs = () => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/sync-jobs/' }, mockSyncJobs, 'integrations.sync_jobs'
);
export const fetchSyncRuns = () => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/sync-runs/' }, mockSyncRuns, 'integrations.sync_runs'
);
export const fetchSyncRunDetail = (id = 1) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/integrations/sync-runs/${id}/` }, mockSyncRunDetail, 'integrations.sync_runs.detail'
);
export const runSyncJobMock = (id = 1) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/integrations/sync-jobs/${id}/run-mock/` }, mockSyncRunDetail, 'integrations.sync_jobs.run_mock'
);
export const disableSyncJob = (id = 1) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/integrations/sync-jobs/${id}/disable/` }, mockSyncJobs, 'integrations.sync_jobs.disable'
);
export const fetchApiSyncTasks = () => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/sync-jobs/' }, mockApiSyncTasks, 'integrations.sync_jobs'
);
export const fetchApiSyncLogs = () => requestWithMockFallback(
  { method: 'get', url: '/api/internal/integrations/sync-runs/' }, mockApiSyncLogs, 'integrations.sync_runs'
);
