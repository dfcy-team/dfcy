import { describe, expect, it, vi } from 'vitest';
import request from '../src/api/request';
import { fetchTikTokDailySpend } from '../src/api/advertising';

vi.mock('../src/api/request', () => ({ default: { get: vi.fn() }, requestApi: vi.fn(), requestPendingOrMock: vi.fn() }));

describe('TikTok spend API', () => {
  it('uses the real read-only API with no mock fallback', async () => {
    request.get.mockResolvedValue({ success: true, data: {} });
    const params = { date_from: '2026-10-01', date_to: '2026-10-02' };
    await fetchTikTokDailySpend(params);
    expect(request.get).toHaveBeenCalledWith('/api/internal/analytics/advertising/tiktok-daily-spend/', {
      params, noMockFallback: true,
    });
  });

  it('propagates rejection rather than fabricating metrics', async () => {
    request.get.mockRejectedValue(new Error('denied'));
    await expect(fetchTikTokDailySpend({})).rejects.toThrow('denied');
  });
});
