import { requestWithMockFallback } from './request';
import { mockPrices } from '../mock/pricing';

export const fetchPrices = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/pricing/prices/' }, mockPrices, 'pricing.prices');

export const fetchPriceDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/pricing/prices/${id}/` }, mockPrices, 'pricing.prices.detail');
