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

  try {
    return await request(config);
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
