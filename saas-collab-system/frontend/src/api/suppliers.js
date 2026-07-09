import { requestWithMockFallback } from './request';
import {
  mockSupplierShipmentDetail,
  mockSupplierShipments,
  mockSupplierTaskDetail,
  mockSupplierTasks
} from '../mock/suppliers';

export const fetchSupplierTasks = () =>
  requestWithMockFallback({ method: 'get', url: '/api/external/supplier/tasks/' }, mockSupplierTasks, 'suppliers.tasks');

export const fetchSupplierTaskDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/external/supplier/tasks/${id}/` }, mockSupplierTaskDetail, 'suppliers.tasks.detail');

export const fetchSupplierShipments = () =>
  requestWithMockFallback({ method: 'get', url: '/api/external/supplier/shipments/' }, mockSupplierShipments, 'suppliers.shipments');

export const fetchSupplierShipmentDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/external/supplier/shipments/${id}/` }, mockSupplierShipmentDetail, 'suppliers.shipments.detail');
