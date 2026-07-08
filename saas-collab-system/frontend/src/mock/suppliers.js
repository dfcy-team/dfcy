import { successResponse } from './index';

export const mockSupplierTasks = () => successResponse({
  status: 'mock',
  module: 'suppliers.tasks',
  items: [
    {
      task_no: 'MOCK-SUPPLIER-TASK-001',
      supplier_name: 'Mock Supplier',
      status: 'pending'
    }
  ]
});

export const mockSupplierShipments = () => successResponse({
  status: 'mock',
  module: 'suppliers.shipments',
  items: [
    {
      shipment_no: 'MOCK-SHIPMENT-001',
      carton_count: 0,
      status: 'pending'
    }
  ]
});
