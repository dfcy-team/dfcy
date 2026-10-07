import axios from 'axios';
import { getMockResponse, normalizeApiError, requestApi, useMock } from './request';
import {
  mockChangeMyPassword,
  mockCurrentUser,
  mockLogin,
  mockMyProfile,
  mockUpdateMyProfile,
} from '../mock/auth';
import { apiBaseUrl } from './baseUrl';

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

async function feishuRequest(method, path) {
  try {
    const response = await axios({ method, url: `${apiBaseUrl}${path}`, withCredentials: true });
    return response.data;
  } catch (error) {
    return normalizeApiError(error);
  }
}

export const getFeishuLoginConfig = () => useMock
  ? Promise.resolve({ success: true, code: 'OK', message: 'success', data: { enabled: false } })
  : feishuRequest('get', '/api/feishu/login/config/');
export const startFeishuLogin = () => useMock
  ? Promise.resolve({ success: false, code: 'config_unavailable', data: null })
  : feishuRequest('post', '/api/feishu/login/start/');
export const completeFeishuLogin = () => useMock
  ? Promise.resolve({ success: false, code: 'provider_error', data: null })
  : feishuRequest('post', '/api/feishu/login/complete/');

export const getCurrentUser = () => {
  if (useMock) return Promise.resolve(getMockResponse(mockCurrentUser, 'auth.me'));
  return requestApi({ method: 'get', url: '/api/internal/auth/me/', params: { include_modules: 1 } });
};

export const getMyProfile = () => {
  if (useMock) return Promise.resolve(getMockResponse(mockMyProfile, 'auth.profile'));
  return requestApi({ method: 'get', url: '/api/internal/auth/profile/' });
};

export const updateMyProfile = (payload) => {
  if (useMock) return Promise.resolve(getMockResponse(() => mockUpdateMyProfile(payload), 'auth.profile.update'));
  return requestApi({ method: 'patch', url: '/api/internal/auth/profile/', data: payload });
};

export const changeMyPassword = (payload) => {
  if (useMock) return Promise.resolve(getMockResponse(mockChangeMyPassword, 'auth.password.change'));
  return requestApi({ method: 'post', url: '/api/internal/auth/password/', data: payload });
};
