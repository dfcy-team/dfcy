import { mockResponse } from './mockResponse'

export function listIntegrations() {
  return mockResponse({ items: [] })
}

export function getIntegrationDetail() {
  return mockResponse()
}
