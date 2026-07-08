import { getMockResponse } from './request';
import { mockPurchaseOrders } from '../mock/purchasing';

export const fetchPurchaseOrders = () => getMockResponse(mockPurchaseOrders, 'purchasing.orders');
