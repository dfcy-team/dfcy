import { successResponse } from './index';

export const mockPurchaseOrders = () => successResponse({
  status: 'mock',
  module: 'purchasing.orders',
  items: [
    {
      purchase_order_no: 'MOCK-PO-001',
      sku: 'MOCK-SKU-001',
      supplier_name: 'Mock Supplier',
      approval_status: 'pending'
    }
  ]
});
