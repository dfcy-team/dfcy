import { requestApi } from './request';

const baseUrl = '/api/internal/purchasing/supply-orders/';

export const fetchSupplyOrders = (params = {}) => requestApi({
  url: baseUrl,
  method: 'get',
  params
});

export const fetchSupplyOrder = (id) => requestApi({
  url: `${baseUrl}${id}/`,
  method: 'get'
});

export const createSupplyOrder = (data) => requestApi({
  url: baseUrl,
  method: 'post',
  data
});

export const runSupplyOrderAction = (id, action, data = {}) => requestApi({
  url: `${baseUrl}${id}/actions/${action}/`,
  method: 'post',
  data
});
