import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  mockIntegrationWorkspace,
  mockSyncAlertIncidentRetryPreview,
  mockSyncAlertIncidents,
} from '../src/mock/integrations';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('integration sync workspace health contract', () => {
  it('requests the frozen workspace endpoint with the sync-jobs page contract', () => {
    const source = read('src/api/integrations.js');
    expect(source).toContain("url: '/api/internal/integrations/workspace/'");
    expect(source).toContain("fetchIntegrationWorkspace('sync-jobs', params)");
    expect(source).toContain('page: 1');
    expect(source).toContain('page_size: 100');
  });

  it('returns backend-shaped health summary and task rows from the mock', () => {
    const response = mockIntegrationWorkspace('sync-jobs');
    expect(response.success).toBe(true);
    expect(response.data).toMatchObject({
      mode: 'sync-jobs',
      api_status: 'mock',
      pagination: { page: 1, page_size: 100 },
      summary: {
        failed_run_count: expect.any(Number),
        retry_waiting_job_count: expect.any(Number),
        retry_exhausted_job_count: expect.any(Number),
        stale_running_job_count: expect.any(Number),
        capability_blocked_job_count: expect.any(Number),
        open_sync_alert_count: expect.any(Number)
      }
    });
    expect(response.data.results[0]).toEqual(expect.objectContaining({
      health_state: expect.any(String),
      schedule_state: expect.any(String),
      blocked_reason: expect.any(String),
      capability_state: expect.any(String),
      capability_code: expect.any(String),
      source_priority: expect.any(Number),
      selected_authorization_id: expect.any(Number),
      latest_error_code: expect.any(String),
      latest_error_message: expect.any(String)
    }));
    expect(response.data.results[0]).toHaveProperty('next_run_at');
  });

  it('renders health, capability, priority, error, and schedule fields without adding real writes', () => {
    const page = read('src/views/integrations/SyncJobList.vue');
    for (const field of [
      'failed_run_count', 'retry_waiting_job_count', 'retry_exhausted_job_count',
      'stale_running_job_count', 'capability_blocked_job_count', 'open_sync_alert_count',
      'health_state', 'schedule_state', 'blocked_reason', 'capability_state',
      'capability_code', 'source_priority', 'selected_authorization_id',
      'latest_error_code', 'latest_error_message', 'next_run_at'
    ]) expect(page).toContain(field);
    expect(page).toContain("permission: 'integrations.run'");
    expect(page).toContain("permission: 'integrations.manage'");
    expect(page).toContain('runSyncJobMock');
    expect(page).toContain('disableSyncJob');
    expect(page).not.toMatch(/\/api\/(external|rpa|finance)\//);
  });

  it('keeps the mock response aligned with the workspace service envelope', () => {
    const response = mockIntegrationWorkspace('sync-jobs');
    expect(response.data).toHaveProperty('scheduler');
    expect(response.data).toHaveProperty('scheduler_history');
    expect(response.data).toHaveProperty('options');
    expect(response.data).toHaveProperty('reference_options');
    expect(response.data).toHaveProperty('previews');
    expect(response.data).toHaveProperty('results');
  });

  it('implements incident handling and preview-confirmed sandbox retry without live writes', () => {
    const api = read('src/api/integrations.js');
    const page = read('src/views/integrations/SyncJobList.vue');
    expect(api).toContain('/api/internal/integrations/sync-alert-incidents/');
    expect(api).toContain('/action/`');
    expect(api).toContain('/retry/`');
    expect(api).toContain('confirmed: true');
    expect(api).toContain('idempotency_key');
    for (const action of ['acknowledge', 'assign', 'note', 'resolve']) expect(page).toContain(action);
    expect(page).toContain('同步事件工作台');
    expect(page).toContain('loadRetryPreview');
    expect(page).toContain('人工重试二次确认');
    expect(page).toContain('external_api_called=false');
    expect(page).toContain("permission: 'integrations.manage'");
    expect(page).toContain("permission: 'integrations.run'");
    expect(page).toContain('至少 3 个字符的处置备注');
    expect(mockSyncAlertIncidents().data.length).toBeGreaterThan(0);
    const preview = mockSyncAlertIncidentRetryPreview(901).data;
    expect(preview.allowed).toBe(true);
    expect(preview.external_api_called).toBe(false);
    expect(preview.requires_confirmation).toBe(true);
  });
});
