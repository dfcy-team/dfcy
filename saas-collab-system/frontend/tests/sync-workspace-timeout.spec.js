import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocked = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('../src/api/request', () => ({ useMock: false, requestWithMockFallback: (...args) => mocked.request(...args) }));
import { fetchSyncJobs, fetchIntegrationWorkspace } from '../src/api/integrations';
describe('sync workspace request budget', () => {
  beforeEach(() => mocked.request.mockReset());
  it('sets a 30 second timeout only on sync workspace reads', () => {
    fetchSyncJobs({ page: 2, page_size: 50 });
    fetchIntegrationWorkspace('sync-runs', { page: 1, page_size: 50 });
    expect(mocked.request).toHaveBeenCalledTimes(2);
    for (const [config] of mocked.request.mock.calls) {
      expect(config).toMatchObject({ method: 'get', url: '/api/internal/integrations/workspace/', timeout: 30000, noMockFallback: true });
      expect(config.params.page_size).toBe(50);
    }
  });
});
