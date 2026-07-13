import axios from 'axios';
import { pendingResponse } from '../mock';

export const useMock = import.meta.env.VITE_USE_MOCK !== 'false';

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 10000
});

export function normalizeApiResponse(payload) {
  if (
    payload &&
    typeof payload === 'object' &&
    'success' in payload &&
    'code' in payload &&
    'message' in payload &&
    'data' in payload
  ) {
    return payload;
  }

  return {
    success: true,
    code: 'OK',
    message: 'success',
    data: payload ?? {}
  };
}

request.interceptors.response.use((response) => normalizeApiResponse(response.data));

function withApiStatus(response, apiStatus) {
  const data = response?.data;
  if (!data || typeof data !== 'object' || Array.isArray(data)) return response;
  return { ...response, data: { ...data, api_status: data.api_status || apiStatus } };
}

export function normalizeApiError(error) {
  const payload = error?.response?.data;
  if (payload && typeof payload === 'object' && 'success' in payload) {
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
        api_status: 'fallback',
        api_error: error?.response?.data?.message || error?.message || 'request failed'
      }
    };
  }
}

export const getMockOrRequest = (moduleName, config, mockHandler) =>
  requestWithMockFallback(config, mockHandler, moduleName);

export default request;
