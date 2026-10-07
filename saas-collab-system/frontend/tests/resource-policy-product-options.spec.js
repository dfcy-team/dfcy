import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestWithMockFallback } = vi.hoisted(() => ({ requestWithMockFallback: vi.fn() }));
vi.mock('../src/api/request', () => ({
  explicitMockMode: vi.fn(), requestApi: vi.fn(),
  requestWithMockFallback: (...args) => requestWithMockFallback(...args),
}));

import { fetchRoleScopeOptions } from '../src/api/systemAdmin';

describe('resource policy product dimensions', () => {
  beforeEach(() => requestWithMockFallback.mockReset().mockResolvedValue({ success: true, data: {} }));

  it('forwards opt-in product search and selected IDs to the bounded options endpoint', async () => {
    const params = {
      include_products: true, product_search: 'old-code',
      selected_sku_ids: '12,13', selected_spu_ids: '7',
    };
    await fetchRoleScopeOptions(params);
    expect(requestWithMockFallback).toHaveBeenCalledWith(
      { method: 'get', url: '/api/internal/system/role-scope-options/', params },
      expect.any(Function), 'system.role_scope_options',
    );
  });
});
