import { requestWithMockFallback } from './request';
import {
  mockStatusDashboard,
  mockStatusRecommendationDetail,
  mockStatusRecommendations,
  mockStatusTransitions
} from '../mock/productStatus';

export const fetchProductStatusDashboard = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/products/status-recommendations/' },
    mockStatusDashboard,
    'products.status.dashboard'
  );

export const fetchProductStatusRecommendations = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/products/status-recommendations/' },
    mockStatusRecommendations,
    'products.status.recommendations'
  );

export const fetchProductStatusRecommendationDetail = (id = 1) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/products/status-recommendations/${id}/` },
    mockStatusRecommendationDetail,
    'products.status.recommendations.detail'
  );

export const confirmProductStatusRecommendation = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/products/status-recommendations/${id}/confirm/` },
    mockStatusRecommendationDetail,
    'products.status.recommendations.confirm'
  );

export const rejectProductStatusRecommendation = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/internal/products/status-recommendations/${id}/reject/` },
    mockStatusRecommendationDetail,
    'products.status.recommendations.reject'
  );

export const fetchProductStatusTransitions = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/products/status-transitions/' },
    mockStatusTransitions,
    'products.status.transitions'
  );

export const evaluateProductStatusMock = () =>
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/products/status/evaluate-mock/' },
    mockStatusRecommendations,
    'products.status.evaluate_mock'
  );
