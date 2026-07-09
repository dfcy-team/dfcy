import { requestWithMockFallback } from './request';
import { mockCurrentUser, mockLogin } from '../mock/auth';

export const login = (data = {}) =>
  requestWithMockFallback({ method: 'post', url: '/api/internal/auth/login/', data }, mockLogin, 'auth.login');

export const getCurrentUser = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/auth/me/' }, mockCurrentUser, 'auth.me');
