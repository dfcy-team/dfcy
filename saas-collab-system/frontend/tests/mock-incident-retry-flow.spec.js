import { beforeEach, expect, it, vi } from 'vitest';
let mock;
beforeEach(async () => { vi.resetModules(); mock = await import('../src/mock/integrations'); });
it('every incident and preview points to a matching source run', () => {
  for (const incident of mock.mockSyncAlertIncidents().data) {
    const preview = mock.mockSyncAlertIncidentRetryPreview(incident.id).data;
    const source = mock.mockIntegrationWorkspace('sync-runs', { sync_job_id: incident.sync_job_id, run_pk: incident.last_sync_run_id }).data.results;
    expect(source).toHaveLength(1);
    expect(source[0]).toMatchObject({ run_id: incident.last_run_id, resource_type: incident.resource_type, environment: preview.environment, execution_mode: preview.execution_mode });
    expect(preview.source_sync_run_id).toBe(source[0].id);
  }
});
it('creates a queryable new run, replays the same intent and preserves history', () => {
  const source = mock.mockIntegrationWorkspace('sync-runs', { run_pk: 303 }).data.results[0];
  const payload = { confirmed: true, idempotency_key: 'retry-intent-001' };
  const result = mock.mockSyncAlertIncidentRetry(901, payload);
  expect(result.data.created).toBe(true);
  const run = result.data.run;
  expect(mock.mockIntegrationWorkspace('sync-runs', { run_pk: run.id, sync_job_id: 1, subject_key: 'store:1' }).data.results).toEqual([run]);
  expect(run).toMatchObject({ status: 'success', external_api_called: false, retry_of: source.run_id, failed_count: 0 });
  expect(mock.mockSyncAlertIncidentRetry(901, payload).data).toMatchObject({ created: false, run: { id: run.id } });
  expect(mock.mockIntegrationWorkspace('sync-runs', { run_pk: 303 }).data.results[0]).toEqual(source);
  expect(mock.mockSyncAlertIncidentRetry(901, { ...payload, idempotency_key: 'retry-intent-002' }).data.run.id).not.toBe(run.id);
});
it('rejects unconfirmed, invalid-key and production requests without new runs', () => {
  const before = mock.mockIntegrationWorkspace('sync-runs').data.pagination.total;
  for (const [id, payload] of [[901, {}], [901, { confirmed: true, idempotency_key: 'short' }], [901, { confirmed: true, idempotency_key: 'x'.repeat(101) }], [902, { confirmed: true, idempotency_key: 'valid-key-002' }]]) {
    expect(mock.mockSyncAlertIncidentRetry(id, payload).success).toBe(false);
  }
  expect(mock.mockIntegrationWorkspace('sync-runs').data.pagination.total).toBe(before);
});
