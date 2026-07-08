import { getMockResponse } from './request';
import { mockSupplierShipments, mockSupplierTasks } from '../mock/suppliers';

export const fetchSupplierTasks = () => getMockResponse(mockSupplierTasks, 'suppliers.tasks');
export const fetchSupplierShipments = () => getMockResponse(mockSupplierShipments, 'suppliers.shipments');
