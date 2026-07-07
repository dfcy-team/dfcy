import { mockResponse } from './mockResponse'

export function listSuppliers() {
  return mockResponse({ items: [] })
}

export function getSupplierDetail() {
  return mockResponse()
}
