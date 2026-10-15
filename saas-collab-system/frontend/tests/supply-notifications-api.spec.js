import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ requestApi: vi.fn(), downloadApiFile: vi.fn(), sequence: 0 }));
vi.mock('../src/api/request', () => ({ requestApi: mocks.requestApi, downloadApiFile: mocks.downloadApiFile }));
vi.mock('../src/api/supplyChainV2', () => ({ createIdempotencyKey: () => `notification-key-${++mocks.sequence}` }));

import * as api from '../src/api/supplyNotificationsV2';
const ok = (data = null) => ({ success: true, data });

describe('notification transport boundary', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.requestApi.mockResolvedValue(ok()); });

  it('uses the binding PUT endpoint with a version and mandatory action key', async () => {
    const body = { expected_version: 2, channel_id: 4, enabled: false };
    await api.saveSupplierNotificationBinding(17, body);
    expect(mocks.requestApi).toHaveBeenCalledWith(expect.objectContaining({
      method: 'put', url: '/api/internal/supply-chain/v2/suppliers/17/notification-binding/', data: body,
      headers: { 'Idempotency-Key': expect.stringMatching(/^notification-key-/) }
    }));
  });

  it('keeps the same key when requestApi resolves an unknown network result', async () => {
    mocks.requestApi.mockResolvedValueOnce({ success: false, http_status: null, code: 'HTTP_NETWORK_ERROR' });
    await api.updateNotificationChannel(91, { expected_version: 2 });
    await api.updateNotificationChannel(91, { expected_version: 2 });
    const [first, second] = mocks.requestApi.mock.calls.map(([value]) => value);
    expect(first.method).toBe('put');
    expect(second.headers['Idempotency-Key']).toBe(first.headers['Idempotency-Key']);
  });

  it('keeps the same key after a server error but renews it after confirmed success', async () => {
    mocks.requestApi.mockResolvedValueOnce({ success: false, http_status: 500 });
    await api.createNotificationChannel({ name: '通道甲' });
    await api.createNotificationChannel({ name: '通道甲' });
    await api.createNotificationChannel({ name: '通道乙' });
    const keys = mocks.requestApi.mock.calls.map(([request]) => request.headers['Idempotency-Key']);
    expect(keys[1]).toBe(keys[0]); expect(keys[2]).not.toBe(keys[0]);
  });

  it('allows correcting a definitively rejected payload with a fresh key', async () => {
    mocks.requestApi.mockResolvedValueOnce({ success: false, http_status: 422 });
    await api.retrySupplyNotificationPart(8, 6, { expected_version: 3, reason: '' });
    await api.retrySupplyNotificationPart(8, 6, { expected_version: 3, reason: '已核实失败' });
    expect(mocks.requestApi.mock.calls[1][0].headers['Idempotency-Key']).not.toBe(mocks.requestApi.mock.calls[0][0].headers['Idempotency-Key']);
  });

  it('downloads material through the authenticated API path', async () => {
    await api.downloadSupplyNotificationPart(8, 3, '采购单.xlsx');
    expect(mocks.downloadApiFile).toHaveBeenCalledWith('/api/internal/supply-chain/v2/notifications/8/parts/3/download/', '采购单.xlsx');
    expect(mocks.requestApi).not.toHaveBeenCalled();
  });

  it('separates credentials, read-only checks and result verification endpoints', async () => {
    await api.setNotificationChannelCredentials(3, { expected_version: 1, robot_id: 'synthetic-only', reason: '本地测试' });
    await api.checkNotificationChannel(3, { expected_version: 2 });
    await api.verifySupplyNotificationPart(9, 7, { expected_version: 4, result: 'delivered', evidence: '本地仿真' });
    expect(mocks.requestApi.mock.calls.map(([r]) => r.url)).toEqual([
      '/api/internal/supply-chain/v2/notification-channels/3/credentials/',
      '/api/internal/supply-chain/v2/notification-channels/3/check/',
      '/api/internal/supply-chain/v2/notifications/9/parts/7/verify/'
    ]);
  });
});
