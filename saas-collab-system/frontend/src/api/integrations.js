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
    { method: 'get', url: '/api/internal/integrations/sync-tasks/' },
    mockApiSyncTasks,
    'integrations.sync_tasks'
  );

export const fetchApiSyncLogs = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/integrations/sync-logs/' },
    mockApiSyncLogs,
    'integrations.sync_logs'
  );
