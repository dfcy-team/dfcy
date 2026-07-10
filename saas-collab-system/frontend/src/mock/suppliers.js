import { successResponse } from './index';

const supplierTask = {
  id: 1,
  supplier_id: 10001,
  task_no: 'MOCK-SUPPLIER-TASK-001',
  sku_code: 'MOCK-SKU-001',
  production_quantity: 300,
  completed_quantity: 120,
  expected_ship_date: '2026-07-30',
  status: 'in_progress',
  is_overdue: false,
  feedback_note: 'mock-feedback-note',
  exception_note: ''
};

const supplierShipment = {
  id: 1,
  supplier_id: 10001,
  shipment_no: 'MOCK-SHIPMENT-001',
  sku_code: 'MOCK-SKU-001',
  ship_quantity: 120,
  carton_count: 12,
  weight: '60.000',
  volume: '1.200',
  shipping_mark: 'MOCK-SHIPPING-MARK',
  tracking_no: 'MOCK-TRACKING-ONLY',
  attachment_placeholder: 'demo-attachment-placeholder',
  status: 'submitted'
};

export const mockSupplierTasks = () => successResponse({
  status: 'mock',
  module: 'suppliers.tasks',
  items: [supplierTask]
});

export const mockSupplierTaskDetail = () => successResponse({
  status: 'mock',
  module: 'suppliers.tasks.detail',
  ...supplierTask
});

export const mockSupplierShipments = () => successResponse({
  status: 'mock',
  module: 'suppliers.shipments',
  items: [supplierShipment]
});

export const mockSupplierShipmentDetail = () => successResponse({
  status: 'mock',
  module: 'suppliers.shipments.detail',
  ...supplierShipment
});
