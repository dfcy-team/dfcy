import { requestApi } from './request';

// Deliberately no mock fallback: unavailable business data must stay unavailable.
export const fetchRealtimeBoard = (params, signal) => requestApi({
  method: 'get', url: '/api/internal/commerce/realtime-board/', params, signal, timeout: 20000
});
export const fetchBoardFilters = () => requestApi({
  method: 'get', url: '/api/internal/commerce/filters/', params: { catalog: 'sales' }, timeout: 12000
});
