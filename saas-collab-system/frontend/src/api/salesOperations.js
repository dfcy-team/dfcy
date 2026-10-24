import { requestApi } from './request';

export const fetchSalesOperations = (params, signal) => requestApi({
  method: 'get', url: '/api/internal/commerce/sales-operations/', params,
  signal, timeout: 20000
});
