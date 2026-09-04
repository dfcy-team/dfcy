import axios from 'axios';
import { pendingResponse } from '../mock';
import {
  clearAuthSession,
  getAccessToken,
  getRefreshToken,
  updateAccessToken
} from '../utils/authSession';
import { apiBaseUrl } from './baseUrl';

export const useMock = import.meta.env.VITE_USE_MOCK !== 'false';
// A production-like build must opt in explicitly before a mutation can be
// simulated.  Keeping this separate from `useMock` lets existing GET-only
// local previews retain their historical behaviour while preventing a failed
// POST/PUT/PATCH/DELETE from being reported as a successful write.
export const explicitMockMode = import.meta.env.VITE_USE_MOCK === 'true';

const MUTATION_METHODS = new Set(['post', 'put', 'patch', 'delete']);

export function isMutationRequest(config = {}) {
  // Some provider callbacks are intentionally exposed as GET endpoints, but
  // still create/replace an authorization on the server.  Callers may mark
  // those requests explicitly; keep the HTTP-method heuristic for every
  // existing POST/PUT/PATCH/DELETE caller.
  return config.mutation === true
    || config.noMockFallback === true
    || MUTATION_METHODS.has(String(config.method || 'get').toLowerCase());
}

const request = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000
});

let refreshPromise = null;
let authenticationExpiredHandler = null;

export function onAuthenticationExpired(handler) {
  authenticationExpiredHandler = handler;
}

export function isApiEnvelope(payload) {
  return Boolean(
    payload &&
      typeof payload === 'object' &&
      !Array.isArray(payload) &&
      typeof payload.success === 'boolean' &&
      typeof payload.code === 'string' &&
      payload.code.length > 0 &&
      typeof payload.message === 'string' &&
      'data' in payload
  );
}

export function normalizeApiResponse(payload) {
  if (isApiEnvelope(payload)) {
    return payload;
  }

  return {
    success: false,
    code: 'INVALID_API_RESPONSE',
    message: 'API response does not match the required envelope.',
    data: null,
    protocol_error: true
  };
}

request.interceptors.request.use((config) => {
  const access = getAccessToken();
  if (access && !config.skipAuth) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

request.interceptors.response.use(
  (response) => normalizeApiResponse(response.data),
  async (error) => {
    const original = error?.config;
    const isAuthenticationRequest = /\/api\/internal\/auth\/(login|refresh)\//.test(original?.url || '');
    const refresh = getRefreshToken();

    if (error?.response?.status === 401 && original && !original._authRetried && !isAuthenticationRequest && refresh) {
      original._authRetried = true;
      refreshPromise ||= axios
        .post(`${apiBaseUrl}/api/internal/auth/refresh/`, { refresh })
        .then((response) => response.data?.access || response.data?.data?.access)
        .finally(() => {
          refreshPromise = null;
        });

      try {
        const access = await refreshPromise;
        if (!access) throw new Error('Refresh response did not include an access token.');
        updateAccessToken(access);
        original.headers = original.headers || {};
        original.headers.Authorization = `Bearer ${access}`;
        return request(original);
      } catch (refreshError) {
        clearAuthSession();
        authenticationExpiredHandler?.();
        return Promise.reject(refreshError);
      }
    }

    if (error?.response?.status === 401 && !isAuthenticationRequest) {
      clearAuthSession();
      authenticationExpiredHandler?.();
    }
    return Promise.reject(error);
  }
);

export function withApiStatus(response, apiStatus) {
  if (response?.success !== true) return response;
  const data = response?.data;
  if (!data || typeof data !== 'object' || Array.isArray(data)) return response;
  return { ...response, data: { ...data, api_status: data.api_status || apiStatus } };
}

export function normalizeApiError(error) {
  const payload = error?.response?.data;
  if (isApiEnvelope(payload)) {
    return { ...normalizeApiResponse(payload), http_status: error.response.status };
  }
  return {
    success: false,
    code: `HTTP_${error?.response?.status || 'NETWORK_ERROR'}`,
    message: error?.message || 'API request failed',
    data: null,
    http_status: error?.response?.status || null
  };
}

export function formatApiError(response) {
  const labels = {
    401: '登录状态无效或已过期',
    403: '当前角色、租户或数据范围无权访问',
    404: '请求的资源不存在或不在可见范围内',
    409: '操作与当前状态冲突，请刷新后重试',
    422: '业务规则或字段校验未通过'
  };
  const status = response?.http_status;
  return `${response?.code || 'API_ERROR'}: ${labels[status] || response?.message || '请求失败'}`;
}

// Downloads are resolved through the same API origin as normal requests.  Do
// not allow an absolute or protocol-relative URL to receive the current
// user's bearer token.
export function isTrustedApiFilePath(value) {
  if (typeof value !== 'string') return false;
  const candidate = value.trim();
  if (!candidate.startsWith('/api/')) return false;
  try {
    const parsed = new URL(candidate, 'https://local-api.invalid');
    return parsed.origin === 'https://local-api.invalid' && parsed.pathname.startsWith('/api/');
  } catch (_error) {
    return false;
  }
}

export async function requestApi(config) {
  try {
    return withApiStatus(await request(config), 'connected');
  } catch (error) {
    return normalizeApiError(error);
  }
}

export async function downloadApiFile(url, filename) {
  if (!isTrustedApiFilePath(url)) {
    return {
      success: false,
      code: 'INVALID_DOWNLOAD_PATH',
      message: '下载地址必须是受信的 /api/ 相对路径。',
      data: null
    };
  }
  try {
    const access = getAccessToken();
    const response = await axios.get(`${import.meta.env.VITE_API_BASE_URL || ''}${url}`, {
      responseType: 'blob',
      headers: access ? { Authorization: `Bearer ${access}` } : {}
    });
    const objectUrl = URL.createObjectURL(response.data);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(objectUrl);
    return { success: true, code: 'OK', message: '文件下载已开始。', data: null };
  } catch (error) {
    return normalizeApiError(error);
  }
}

export function getMockResponse(mockHandler, moduleName) {
  if (typeof mockHandler === 'function') {
    return normalizeApiResponse(mockHandler());
  }
  return normalizeApiResponse(pendingResponse(moduleName));
}

export function requestPendingOrMock(mockHandler, moduleName) {
  if (useMock) return getMockResponse(mockHandler, moduleName);
  return normalizeApiResponse(pendingResponse(moduleName));
}

export async function requestWithMockFallback(config, mockHandler, moduleName) {
  const mutation = isMutationRequest(config);

  // Only an explicit VITE_USE_MOCK=true build may short-circuit writes into
  // fixtures.  This is the deliberate local演练 path.
  if (explicitMockMode) {
    return getMockResponse(mockHandler, moduleName);
  }

  // Preserve the existing implicit mock behaviour for read-only local pages;
  // mutation requests continue to the API so a network failure is visible.
  if (useMock && !mutation) {
    return getMockResponse(mockHandler, moduleName);
  }

  const response = await requestApi(config);
  if (response.success) {
    return response;
  }

  // Never turn a failed mutation into a successful fixture response.  HTTP
  // errors were already returned above in their normalized envelope; this
  // branch also closes the network-error path where no http_status exists.
  if (mutation) {
    return response;
  }

  if (response.http_status) {
    return response;
  }

  try {
    throw new Error(response.message);
  } catch (error) {
    const fallback = getMockResponse(mockHandler, moduleName);
    const fallbackData =
      fallback.data && typeof fallback.data === 'object' && !Array.isArray(fallback.data)
        ? fallback.data
        : { value: fallback.data };

    return {
      ...fallback,
      message: error?.response?.data?.message || error?.message || 'API request failed, fallback to mock data',
      data: {
        ...fallbackData,
        api_status: 'degraded',
        api_error: error?.response?.data?.message || error?.message || 'request failed'
      }
    };
  }
}

export const getMockOrRequest = (moduleName, config, mockHandler) =>
  requestWithMockFallback(config, mockHandler, moduleName);

export default request;
