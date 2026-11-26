import { describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('../src/api/request', () => ({ requestApi: mocks.request, requestWithMockFallback: vi.fn() }));
import { fetchMonthlySalesProgress } from '../src/api/salesManagement';

describe('dashboard request cancellation contract', () => {
  it('passes the abort signal without changing selected scope or month', () => {
    const controller = new AbortController();
    fetchMonthlySalesProgress([11, 12], 3, '2026-10', { signal: controller.signal });
    const config = mocks.request.mock.lastCall[0];
    expect(config.signal).toBe(controller.signal);
    expect(config.params).toEqual({ store_ids: '11,12', platform_id: 3, month: '2026-10' });
    controller.abort();
    expect(config.signal.aborted).toBe(true);
  });
  it('keeps the default all permitted stores request without a store restriction', () => {
    fetchMonthlySalesProgress([], null, '2026-11');
    expect(mocks.request.mock.lastCall[0].params).toEqual({ month: '2026-11' });
  });
});
