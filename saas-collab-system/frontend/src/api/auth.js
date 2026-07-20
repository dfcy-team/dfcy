import axios from 'axios';
import { getMockResponse, normalizeApiError, requestApi, useMock } from './request';
import { mockCurrentUser, mockLogin } from '../mock/auth';

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '';

export function normalizeLoginResponse(payload) {
  if (payload?.access && payload?.refresh) {
    return {
      success: true,
      code: 'OK',
      message: 'success',
      data: { access: payload.access, refresh: payload.refresh }
    };
  }
  return {
    success: false,
    code: 'INVALID_AUTH_RESPONSE',
    message: 'Authentication response did not include access and refresh tokens.',
    data: null
  };
}

export const login = async (data = {}) => {
  if (useMock) return Promise.resolve(getMockResponse(mockLogin, 'auth.login'));
  try {
    const response = await axios.post(`${apiBaseUrl}/api/internal/auth/login/`, data);
    return normalizeLoginResponse(response.data);
  } catch (error) {
    return normalizeApiError(error);
  }
};

export const getCurrentUser = () => {
  if (useMock) return Promise.resolve(getMockResponse(mockCurrentUser, 'auth.me'));
  return requestApi({ method: 'get', url: '/api/internal/auth/me/' });
};
