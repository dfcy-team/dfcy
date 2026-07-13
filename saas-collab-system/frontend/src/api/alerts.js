import { requestWithMockFallback } from './request';
import { mockBusinessAlerts } from '../mock/alerts';

export const fetchBusinessAlerts = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/alerts/business/', params },
    mockBusinessAlerts,
    'alerts.business'
  );
