import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestApi } = vi.hoisted(() => ({ requestApi: vi.fn() }));
vi.mock('../src/api/request', () => ({
  requestApi,
  requestWithMockFallback: vi.fn(),
}));

import { fetchCountryInventoryDecisions, createCountryOperatingOrder } from '../src/api/inventoryDecisions';
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
  it('uses the aggregate read budget only for country summary, preserving writes', async () => {
    const params = { country_id: 2, limit: 20 };
    await fetchCountryInventoryDecisions(params);
    expect(requestApi).toHaveBeenLastCalledWith({method:'get',url:'/api/internal/commerce/inventory/country-decisions/',params,timeout:30000});
    await createCountryOperatingOrder({ country_id: 2 }, 'test-key');
    expect(requestApi.mock.calls.at(-1)[0]).not.toHaveProperty('timeout');
  });

});
