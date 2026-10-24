import { requestApi } from './request';

// Deliberately no mock fallback: unavailable business data must stay unavailable.
export const fetchRealtimeBoard = (params, signal) => requestApi({
  method: 'get', url: '/api/internal/commerce/realtime-board/', params, signal, timeout: 20000
});
export const fetchBoardFilters = () => requestApi({
  method: 'get', url: '/api/internal/commerce/filters/', params: { catalog: 'sales' }, timeout: 12000
});

// Loaded only when the decline view is opened; not part of board polling.
export const fetchBoardDeclines = (params, signal) => requestApi({
  method: 'get', url: '/api/internal/commerce/board-declines/', params, signal, timeout: 20000
});
