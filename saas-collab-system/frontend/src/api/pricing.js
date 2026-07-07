import { mockResponse } from './mockResponse'

export function listPrices() {
  return mockResponse({ items: [] })
}

export function getPricingRuleDetail() {
  return mockResponse()
}
