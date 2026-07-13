import { requestApi, requestWithMockFallback } from './request';
import { mockLifecycleDecisions, mockLifecycleReviews } from '../mock/lifecycle';

export const fetchLifecycleReviews = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/lifecycle/reviews/', params },
    mockLifecycleReviews,
    'lifecycle.reviews'
  );

export const fetchLifecycleDecisions = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/lifecycle/decisions/', params },
    mockLifecycleDecisions,
    'lifecycle.decisions'
  );

export const fetchLifecycleReview = (id) => requestApi({ method: 'get', url: `/api/internal/lifecycle/reviews/${id}/` });
export const evaluateLifecycleMock = (payload) => requestApi({ method: 'post', url: '/api/internal/lifecycle/evaluate-mock/', data: payload });
export const confirmLifecycleReview = (id, payload) => requestApi({ method: 'post', url: `/api/internal/lifecycle/reviews/${id}/confirm/`, data: payload });
export const rejectLifecycleReview = (id, payload) => requestApi({ method: 'post', url: `/api/internal/lifecycle/reviews/${id}/reject/`, data: payload });
