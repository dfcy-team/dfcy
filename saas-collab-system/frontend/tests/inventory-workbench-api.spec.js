import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestApi } = vi.hoisted(() => ({ requestApi: vi.fn() }));
vi.mock('../src/api/request', () => ({
  requestApi,
  requestWithMockFallback: vi.fn(),
}));

import { fetchInventoryWorkbench } from '../src/api/analytics';

describe('inventory workbench request', () => {
  beforeEach(() => requestApi.mockReset());

  it('allows the optimized aggregate request longer than the global 10-second limit', async () => {
    const signal = new AbortController().signal;
    await fetchInventoryWorkbench({ perspective: 'operations' }, { signal });
    expect(requestApi).toHaveBeenCalledWith({
      method: 'get',
      url: '/api/internal/commerce/inventory/workbench/',
      params: { perspective: 'operations' },
      signal,
      timeout: 30000,
    });
  });
});
