import { mockResponse } from './mockResponse'

export function listListings() {
  return mockResponse({ items: [] })
}

export function getListingDetail() {
  return mockResponse()
}
