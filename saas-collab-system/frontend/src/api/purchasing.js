import { requestWithMockFallback } from './request';
import { mockPurchaseOrderDetail, mockPurchaseOrders } from '../mock/purchasing';

export const fetchPurchaseOrders = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/purchasing/orders/' }, mockPurchaseOrders, 'purchasing.orders');

export const fetchPurchaseOrderDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/purchasing/orders/${id}/` }, mockPurchaseOrderDetail, 'purchasing.orders.detail');
