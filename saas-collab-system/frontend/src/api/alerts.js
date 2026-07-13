import { requestApi, requestWithMockFallback } from './request';
import { mockBusinessAlerts } from '../mock/alerts';

export const fetchBusinessAlerts = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/alerts/business/', params },
    mockBusinessAlerts,
    'alerts.business'
  );

export const fetchBusinessAlert = (id) => requestApi({ method: 'get', url: `/api/internal/alerts/business/${id}/` });
export const evaluateBusinessAlertsMock = (payload) => requestApi({ method: 'post', url: '/api/internal/alerts/business/evaluate-mock/', data: payload });
export const assignBusinessAlert = (id, payload) => requestApi({ method: 'post', url: `/api/internal/alerts/business/${id}/assign/`, data: payload });
export const silenceBusinessAlert = (id, payload) => requestApi({ method: 'post', url: `/api/internal/alerts/business/${id}/silence/`, data: payload });
export const closeBusinessAlert = (id, payload) => requestApi({ method: 'post', url: `/api/internal/alerts/business/${id}/close/`, data: payload });

export const fetchInventoryAlerts = (params = {}) => requestApi({ method: 'get', url: '/api/internal/alerts/inventory/', params });
export const fetchInventoryAlert = (id) => requestApi({ method: 'get', url: `/api/internal/alerts/inventory/${id}/` });
export const evaluateInventoryAlertsMock = (payload) => requestApi({ method: 'post', url: '/api/internal/alerts/inventory/evaluate-mock/', data: payload });
export const assignInventoryAlert = (id, payload) => requestApi({ method: 'post', url: `/api/internal/alerts/inventory/${id}/assign/`, data: payload });
export const silenceInventoryAlert = (id, payload) => requestApi({ method: 'post', url: `/api/internal/alerts/inventory/${id}/silence/`, data: payload });
export const closeInventoryAlert = (id, payload) => requestApi({ method: 'post', url: `/api/internal/alerts/inventory/${id}/close/`, data: payload });
