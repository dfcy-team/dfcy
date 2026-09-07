import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const axiosMocks = vi.hoisted(() => ({
  request: vi.fn(),
  create: vi.fn(),
  post: vi.fn(),
}));

vi.mock('axios', () => {
  const instance = axiosMocks.request;
  instance.interceptors = {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  };
  axiosMocks.create.mockReturnValue(instance);
  return {
    default: {
      create: axiosMocks.create,
      post: axiosMocks.post,
    },
  };
});

let requestWithMockFallback;
let completeSyntheticStoreAuthorization;
let mappingReads;

beforeAll(async () => {
  // This suite exercises production-like network failure handling even when
  // the caller runs the wider frontend suite with VITE_USE_MOCK=true.
  vi.stubEnv('VITE_USE_MOCK', 'false');
  vi.resetModules();
  ({ requestWithMockFallback } = await import('../src/api/request'));
  ({ completeSyntheticStoreAuthorization } = await import('../src/api/integrations'));
  const integrationApi = await import('../src/api/integrations');
  mappingReads = [integrationApi.fetchStoreMappings, integrationApi.fetchProductMappings,
    integrationApi.fetchStoreMappingOptions, integrationApi.fetchProductMappingOptions];
});

afterAll(() => vi.unstubAllEnvs());

describe('requestWithMockFallback mutation safety', () => {
  beforeEach(() => {
    axiosMocks.request.mockReset();
    axiosMocks.create.mockClear();
    axiosMocks.post.mockReset();
    axiosMocks.request.mockRejectedValue(new Error('network unavailable'));
  });

  it.each(['post', 'put', 'patch', 'delete'])('returns success=false for %s network failures and does not use a successful mock', async (method) => {
    const mockHandler = vi.fn(() => ({ success: true, code: 'OK', message: 'mock write', data: { written: true } }));
    const response = await requestWithMockFallback(
      { method, url: '/api/internal/test-resource/' },
      mockHandler,
      'request-layer.mutation',
    );

    expect(response.success).toBe(false);
    expect(response.code).toBe('HTTP_NETWORK_ERROR');
    expect(response.data).toBeNull();
    expect(mockHandler).not.toHaveBeenCalled();
  });

  it('retains GET mock fallback behavior after a network failure', async () => {
    const mockHandler = vi.fn(() => ({ success: true, code: 'OK', message: 'mock read', data: { value: 1 } }));
    const response = await requestWithMockFallback(
      { method: 'get', url: '/api/internal/test-resource/' },
      mockHandler,
      'request-layer.read',
    );

    expect(response.success).toBe(true);
    expect(response.data).toMatchObject({ value: 1 });
  });

  it('treats the OAuth callback GET as a mutating production request', async () => {
    const response = await completeSyntheticStoreAuthorization('shopee', { state: 'state-from-provider' });

    expect(response.success).toBe(false);
    expect(response.code).toBe('HTTP_NETWORK_ERROR');
    expect(axiosMocks.request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'get',
      mutation: true,
      noMockFallback: true,
      url: '/api/internal/integrations/store-authorizations/oauth/callback/shopee/',
    }));
  });

  it('never presents rehearsal identities as real mapping choices when production reads fail', async () => {
    for (const read of mappingReads) {
      const response = await read({ store_id: 1 });
      expect(response.success).toBe(false);
      expect(response.code).toBe('HTTP_NETWORK_ERROR');
      expect(response.data).toBeNull();
    }
  });
});
