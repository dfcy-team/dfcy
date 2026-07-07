import { mockResponse } from './mockResponse'

export function listAuditLogs() {
  return mockResponse({ items: [] })
}

export function getAuditLogDetail() {
  return mockResponse()
}
