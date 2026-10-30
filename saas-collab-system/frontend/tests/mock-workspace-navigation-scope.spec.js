import { describe, expect, it } from 'vitest';
import { mockIntegrationWorkspace } from '../src/mock/integrations';
const rows = (mode, params) => mockIntegrationWorkspace(mode, params).data.results;
describe('workspace navigation scope', () => {
  it('selects only the linked task and its runs', () => {
    expect(rows('sync-jobs', { sync_job_id: '1' }).map(r => r.id)).toEqual([1]);
    expect(rows('sync-runs', { sync_job_id: '1' }).map(r => r.id)).toEqual([301, 303]);
  });
  it('intersects the exact run with task scope and never falls back to all data', () => {
    expect(rows('sync-runs', { run_pk: '302', sync_job_id: '4' }).map(r => r.id)).toEqual([302]);
    expect(rows('sync-runs', { run_pk: '302', sync_job_id: '1' })).toEqual([]);
    expect(rows('sync-runs', { run_pk: '999999' })).toEqual([]);
  });
  it('keeps warehouse and store identities separate even when numeric IDs match', () => {
    expect(rows('sync-jobs', { subject_key: 'store:1' }).map(r => r.id)).toEqual([1, 2, 4]);
    expect(rows('sync-jobs', { subject_key: 'warehouse:1' }).map(r => r.id)).toEqual([3]);
    expect(rows('sync-runs', { subject_key: 'warehouse:1' })).toEqual([]);
    expect(rows('sync-runs', { subject_key: 'store:1' })).toHaveLength(4);
    expect(rows('sync-jobs', { subject_key: 'store:999' })).toEqual([]);
  });
});

it('paginates after scope filtering and clamps out-of-range pages', () => {
  const response = mockIntegrationWorkspace('sync-runs', { sync_job_id: '1,4', page: 99, page_size: 1 }).data;
  expect(response.pagination).toEqual({ page: 3, page_size: 1, total: 3, page_count: 3 });
  expect(response.results.map(r => r.id)).toEqual([303]);
  expect(mockIntegrationWorkspace('sync-runs', { run_pk: '999', page: 99 }).data.pagination).toEqual({ page: 1, page_size: 50, total: 0, page_count: 1 });
});

it('uses backend page-size boundaries', () => {
  expect(mockIntegrationWorkspace('sync-runs', { page_size: 0 }).data.pagination.page_size).toBe(1);
  expect(mockIntegrationWorkspace('sync-runs', { page_size: 1000 }).data.pagination.page_size).toBe(100);
});
