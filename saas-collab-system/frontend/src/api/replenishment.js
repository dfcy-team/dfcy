import { requestApi, requestWithMockFallback } from './request';
import { mockReplenishmentRecommendations } from '../mock/replenishment';

export const fetchReplenishmentRecommendations = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/replenishment/recommendations/', params },
    mockReplenishmentRecommendations,
    'replenishment.recommendations'
  );

export const fetchReplenishmentRecommendation = (id) => requestApi({ method: 'get', url: `/api/internal/replenishment/recommendations/${id}/` });
export const evaluateReplenishmentMock = (payload) => requestApi({ method: 'post', url: '/api/internal/replenishment/evaluate-mock/', data: payload });
export const acceptReplenishmentRecommendation = (id, payload) => requestApi({ method: 'post', url: `/api/internal/replenishment/recommendations/${id}/accept/`, data: payload });
export const rejectReplenishmentRecommendation = (id, payload) => requestApi({ method: 'post', url: `/api/internal/replenishment/recommendations/${id}/reject/`, data: payload });
