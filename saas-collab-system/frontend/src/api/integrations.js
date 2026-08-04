import { createIdempotencyKey, requestWithMockFallback } from './request';
import {
  mockApiSyncLogs,
  mockApiSyncTasks,
  mockIntegrationConfigDetail,
  mockIntegrationConfigs,
  mockSyncJobs,
  mockSyncRunDetail,
  mockSyncRuns,
  mockMarketplaceOAuthAction,
  mockMarketplaceOAuthInitiate,
  mockMarketplaceOAuthRetry,
  mockMarketplaceOAuthStatus
} from '../mock/integrations';

const oauthRequest = (config = {}, handler) => requestWithMockFallback(
  {
    ...config,
    headers: { ...(config.headers || {}), 'Idempotency-Key': config.headers?.['Idempotency-Key'] || createIdempotencyKey('oauth') }
  },
  handler,
  'integrations.oauth'
);

const asMockStatus = (response) => {
  if (!response?.success || !response.data || typeof response.data !== 'object') return response;
  return { ...response, data: { ...response.data, api_status: 'mock' } };
};

export const fetchIntegrationConfigs = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/configs/' },
    mockIntegrationConfigs,
    'integrations.configs'
  );

export const fetchIntegrationConfigDetail = (id = 1) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/integrations/configs/${id}/` },
    mockIntegrationConfigDetail,
    'integrations.configs.detail'
  );

export const updateIntegrationConfig = (id, payload) =>
  requestWithMockFallback(
    { method: 'patch', url: `/api/internal/integrations/configs/${id}/`, data: payload },
    mockIntegrationConfigDetail,
    'integrations.configs.update'
  );

export const disableIntegrationConfig = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/disable/`, data: {} },
    mockIntegrationConfigDetail,
    'integrations.configs.disable'
  );

export const verifyIntegrationConfig = (id) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/verify/`, data: {} },
    mockIntegrationConfigDetail,
    'integrations.configs.verify'
  );

export const fetchSyncJobs = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-jobs/' },
    mockSyncJobs,
    'integrations.sync_jobs'
  );

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

export const initiateMarketplaceOAuth = (payload) => oauthRequest(
  { method: 'post', url: '/api/internal/integrations/store-authorizations/oauth/initiate/', data: payload },
  mockMarketplaceOAuthInitiate
).then(asMockStatus);

export const fetchMarketplaceOAuthAttempt = (id) => oauthRequest(
  { method: 'get', url: `/api/internal/integrations/oauth-attempts/${id}/` },
  () => mockMarketplaceOAuthStatus(id)
).then(asMockStatus);

export const refreshMarketplaceAuthorization = (id, scenario = '') => oauthRequest(
  { method: 'post', url: `/api/internal/integrations/store-authorizations/${id}/refresh/`, data: scenario ? { scenario } : {} },
  mockMarketplaceOAuthAction
).then(asMockStatus);

export const revokeMarketplaceAuthorization = (id, scenario = '') => oauthRequest(
  { method: 'post', url: `/api/internal/integrations/store-authorizations/${id}/revoke/`, data: scenario ? { scenario } : {} },
  mockMarketplaceOAuthAction
).then(asMockStatus);

export const retryMarketplaceAuthorization = (id) => oauthRequest(
  { method: 'post', url: `/api/internal/integrations/store-authorizations/${id}/retry/`, data: {} },
  mockMarketplaceOAuthRetry
).then(asMockStatus);
