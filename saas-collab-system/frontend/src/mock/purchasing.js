import { successResponse } from './index';

const purchaseOrder = {
  id: 1,
  po_no: 'MOCK-PO-001',
  sku_code: 'MOCK-SKU-001',
  supplier_id: 10001,
  quantity: 300,
  unit_price: '12.50',
  delivery_date: '2026-07-30',
  payment_terms: 'mock-payment-terms',
  status: 'draft',
  approval_status: 'pending'
};

export const mockPurchaseOrders = () => successResponse({
  status: 'mock',
  module: 'purchasing.orders',
  items: [purchaseOrder]
});

export const mockPurchaseOrderDetail = () => successResponse({
  status: 'mock',
  module: 'purchasing.orders.detail',
  ...purchaseOrder
});
