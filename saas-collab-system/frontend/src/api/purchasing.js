import { mockResponse } from './mockResponse'

export function listPurchaseOrders() {
  return mockResponse({ items: [] })
}

export function getPurchaseOrderDetail() {
  return mockResponse()
}
