import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ requestApi: vi.fn(), requestWithMockFallback: vi.fn() }));
vi.mock('../src/api/request', () => api);
import { fetchIntegrationAudit } from '../src/api/integrations';
import { fetchSalesFilters, fetchSalesPage } from '../src/api/salesManagement';
beforeEach(() => { vi.clearAllMocks(); });
afterEach(() => vi.unstubAllEnvs());
describe('正式读取与目录权限分离', () => {
  it('never falls back to sandbox audit events after a production network failure', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false');
    const failure = { success: false, message: '读取失败', data: null };
    api.requestApi.mockResolvedValue(failure);
    expect(await fetchIntegrationAudit({ page: 1 })).toBe(failure);
    expect(api.requestWithMockFallback).not.toHaveBeenCalled();
    expect(api.requestApi).toHaveBeenCalledWith(expect.objectContaining({url:'/api/internal/integrations/audit/'}));
  });
  it('keeps deliberate mock-mode audit fixtures available', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true');
    await fetchIntegrationAudit();
    expect(api.requestWithMockFallback).toHaveBeenCalledTimes(1);
    expect(api.requestApi).not.toHaveBeenCalled();
  });
  it('uses the quality permission endpoint for the quality catalogue only', async () => {
    await fetchSalesFilters({catalog:'quality'});
    expect(api.requestWithMockFallback).toHaveBeenLastCalledWith(expect.objectContaining({url:'/api/internal/commerce/quality/',params:{catalog:'quality'}}),expect.any(Function),'sales_management.filters');
    await fetchSalesFilters({catalog:'sales'});
    expect(api.requestWithMockFallback).toHaveBeenLastCalledWith(expect.objectContaining({url:'/api/internal/commerce/filters/'}),expect.any(Function),'sales_management.filters');
  });
  it('projects quality summaries with a longer timeout and leaves ordinary lists unchanged', async () => {
    await fetchSalesPage('data-quality', { include_summary: 'true', page: 1 });
    expect(api.requestWithMockFallback).toHaveBeenLastCalledWith(
      expect.objectContaining({
        url: '/api/internal/commerce/quality/', timeout: 60000,
        params: { include_summary: 'true', page: 1, summary_projection: 'quality' }
      }), expect.any(Function), 'sales_management.data-quality'
    );
    await fetchSalesPage('orders', { page: 1 });
    expect(api.requestWithMockFallback).toHaveBeenLastCalledWith(
      expect.objectContaining({ url: '/api/internal/commerce/orders/', params: { page: 1 } }),
      expect.any(Function), 'sales_management.orders'
    );
    await fetchSalesPage('data-quality', { include_summary: 'false' });
    expect(api.requestWithMockFallback).toHaveBeenLastCalledWith(
      expect.objectContaining({ url: '/api/internal/commerce/quality/', params: { include_summary: 'false' } }),
      expect.any(Function), 'sales_management.data-quality'
    );
  });
});
