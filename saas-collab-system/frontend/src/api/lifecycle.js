import { requestWithMockFallback } from './request';
import { mockLifecycleHistory, mockLifecycleReviews } from '../mock/lifecycle';

export const fetchLifecycleReviews = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/lifecycle/reviews/', params },
    mockLifecycleReviews,
    'lifecycle.reviews'
  );

export const fetchLifecycleHistory = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/lifecycle/history/', params },
    mockLifecycleHistory,
    'lifecycle.history'
  );
