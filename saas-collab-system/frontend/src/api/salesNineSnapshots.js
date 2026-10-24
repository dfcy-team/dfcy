import { requestApi } from './request';

export const fetchSalesNineSnapshots = (params, signal) => requestApi({
  method: 'get', url: '/api/internal/commerce/sales-nine-snapshots/', params,
  signal, timeout: 20000
});
