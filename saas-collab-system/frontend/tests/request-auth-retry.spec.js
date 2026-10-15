import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ request: vi.fn(), refresh: vi.fn(), file: vi.fn(), rejected: null,
  clear: vi.fn(), update: vi.fn(), channel: 'internal' }));
vi.mock('axios', () => ({ default: {
  create: () => {
    mocks.request.interceptors = { request: { use: vi.fn() },
      response: { use: (_resolved, rejected) => { mocks.rejected = rejected; } } };
    return mocks.request;
  },
  post: mocks.refresh,
  get: mocks.file,
} }));
vi.mock('../src/utils/authSession', () => ({
  getAccessToken: () => 'TEST_ACCESS', getRefreshToken: () => 'TEST_REFRESH',
  clearAuthSession: mocks.clear, updateAccessToken: mocks.update,
  readAuthSession: () => ({ channel: mocks.channel }),
}));
import { downloadApiFile } from '../src/api/request';

function failure(code) {
  return { config: { method: 'post', url: '/api/internal/integrations/store-authorizations/oauth/manual-callback/' },
    response: { status: 401, data: { success: false, code, message: 'controlled failure', data: null } } };
}

describe('login renewal versus provider authorization failure', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.channel = 'internal'; });
  it('does not replay a provider-rejected callback or clear the local login', async () => {
    const error = failure('API_SYNC_FAILED');
    await expect(mocks.rejected(error)).rejects.toBe(error);
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(mocks.request).not.toHaveBeenCalled();
    expect(mocks.clear).not.toHaveBeenCalled();
  });
  it('does not replay a one-time callback after local login expiration', async () => {
    const error = failure('AUTH_REQUIRED');
    await expect(mocks.rejected(error)).rejects.toBe(error);
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(mocks.request).not.toHaveBeenCalled();
    expect(mocks.clear).toHaveBeenCalledTimes(1);
  });
  it('continues to renew ordinary requests once', async () => {
    const error = failure('AUTH_REQUIRED');
    error.config.url = '/api/internal/integrations/configs/';
    error.config.data = { callback_url: 'https://example.test/?state=TEST&code=TEST' };
    mocks.refresh.mockResolvedValue({ data: { access: 'TEST_NEW_ACCESS' } });
    mocks.request.mockResolvedValue({ success: true });
    await expect(mocks.rejected(error)).resolves.toEqual({ success: true });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    expect(mocks.request).toHaveBeenCalledWith(expect.objectContaining({ _authRetried: true, data: error.config.data }));
    expect(mocks.clear).not.toHaveBeenCalled();
  });
  it('does not renew a second time when the retried login is rejected', async () => {
    const error = failure('AUTH_REQUIRED');
    error.config._authRetried = true;
    await expect(mocks.rejected(error)).rejects.toBe(error);
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(mocks.clear).toHaveBeenCalledTimes(1);
  });
  it('renews supplier requests through the supplier channel and preserves the original write', async () => {
    mocks.channel = 'supplier_web';
    const error = failure('AUTH_REQUIRED');
    error.config.url = '/api/external/supplier/supply-chain/v2/shipments/';
    error.config.headers = { 'Idempotency-Key': 'same-write-key' };
    error.config.data = { order_id: 7 };
    mocks.refresh.mockResolvedValue({ data: { access: 'SUPPLIER_ACCESS' } });
    mocks.request.mockResolvedValue({ success: true });
    await expect(mocks.rejected(error)).resolves.toEqual({ success: true });
    expect(mocks.refresh.mock.calls[0][0]).toMatch(/\/api\/external\/auth\/refresh\/$/);
    expect(mocks.request.mock.calls[0][0].headers['Idempotency-Key']).toBe('same-write-key');
  });
  it('renews a supplier download once and retries the same authorized file path', async () => {
    mocks.channel = 'supplier_web';
    mocks.file.mockRejectedValueOnce({response:{status:401}}).mockResolvedValueOnce({data:new Blob(['boxes'])});
    mocks.refresh.mockResolvedValue({data:{access:'SUPPLIER_FILE_ACCESS'}});
    URL.createObjectURL = vi.fn(() => 'blob:test'); URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
    const response = await downloadApiFile('/api/external/supplier/supply-chain/v2/shipments/7/attachments/8/download/', 'boxes.csv');
    expect(response.success).toBe(true);
    expect(mocks.refresh.mock.calls[0][0]).toMatch(/\/api\/external\/auth\/refresh\/$/);
    expect(mocks.file).toHaveBeenCalledTimes(2);
    expect(mocks.file.mock.calls[1][1].headers.Authorization).toBe('Bearer SUPPLIER_FILE_ACCESS');
    click.mockRestore();
  });
});
