import { getMockResponse, requestApi, useMock } from './request';
import { mockCurrentUser, mockLogin } from '../mock/auth';

export const login = (data = {}) => {
  if (useMock) return Promise.resolve(getMockResponse(mockLogin, 'auth.login'));
  return requestApi({ method: 'post', url: '/api/internal/auth/login/', data, skipAuth: true });
};

export const getCurrentUser = () => {
  if (useMock) return Promise.resolve(getMockResponse(mockCurrentUser, 'auth.me'));
  return requestApi({ method: 'get', url: '/api/internal/auth/me/' });
};
