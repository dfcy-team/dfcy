import { requestWithMockFallback } from './request';
import {
  mockApiSyncLogs,
  mockApiSyncTasks,
  mockIntegrationConfigDetail,
  mockIntegrationConfigs,
  mockSyncJobs,
  mockSyncRunDetail,
  mockSyncRuns
} from '../mock/integrations';

export const fetchIntegrationConfigs = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/configs/', params },
    mockIntegrationConfigs,
    'integrations.configs'
  );

export const fetchIntegrationConfigDetail = (id = 1) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/integrations/configs/${id}/` },
    mockIntegrationConfigDetail,
    'integrations.configs.detail'
  );

export const createIntegrationConfig = (payload) =>
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/integrations/workspace-configs/', data: payload },
    mockIntegrationConfigDetail,
    'integrations.configs.create'
  );

export const rotateIntegrationSecretValues = (id, payload, idempotencyKey) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/integrations/configs/${id}/credentials/rotate/`, data: payload, headers: { 'Idempotency-Key': idempotencyKey } },
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

export const fetchSyncJobs = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-jobs/', params },
    mockSyncJobs,
    'integrations.sync_jobs'
  );

export const fetchSyncRuns = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-runs/', params },
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

const emptyWorkspace = (mode) => () => ({
  success: true,
  code: 'OK',
  message: 'Mock API integration workspace',
  data: {
    mode,
    source_status: 'mock',
    summary: {},
    scheduler: { configured: false },
    options: {},
    regions: [],
    previews: {},
    pagination: { page: 1, page_size: 50, total: 0, page_count: 1 },
    results: []
  }
});

export const fetchIntegrationWorkspace = (mode, params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/workspace/', params: { mode, ...params } },
    emptyWorkspace(mode),
    `integrations.workspace.${mode}`
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
