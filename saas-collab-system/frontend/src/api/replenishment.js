import { requestWithMockFallback } from './request';
import { mockInventoryAlerts, mockReplenishmentSuggestions } from '../mock/replenishment';

export const fetchInventoryAlerts = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/alerts/inventory/', params },
    mockInventoryAlerts,
    'replenishment.alerts'
  );

export const fetchReplenishmentSuggestions = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/replenishment/recommendations/', params },
    mockReplenishmentSuggestions,
    'replenishment.suggestions'
  );
