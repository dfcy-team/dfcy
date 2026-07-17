import axios from 'axios';
import { pendingResponse } from '../mock';
import {
  clearAuthSession,
  getAccessToken,
  getRefreshToken,
  updateAccessToken
} from '../utils/authSession';

export const useMock = import.meta.env.VITE_USE_MOCK !== 'false';

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
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
        .post(`${import.meta.env.VITE_API_BASE_URL || ''}/api/internal/auth/refresh/`, { refresh })
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

export async function requestApi(config) {
  try {
    return withApiStatus(await request(config), 'connected');
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
  if (useMock) {
    return getMockResponse(mockHandler, moduleName);
  }

  const response = await requestApi(config);
  if (response.success) {
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
