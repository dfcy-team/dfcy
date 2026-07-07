import { mockResponse } from './mockResponse'

export function listProducts() {
  return mockResponse({ items: [] })
}

export function getProductDetail() {
  return mockResponse()
}

export function listProductResearch() {
  return mockResponse({ items: [] })
}
