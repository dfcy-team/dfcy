import { requestWithMockFallback } from './request';
import { mockListingTemplates, mockSiteProfiles } from '../mock/listings';

export const fetchSiteProfiles = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/listings/sites/' }, mockSiteProfiles, 'listings.sites');

export const fetchSiteProfileDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/listings/sites/${id}/` }, mockSiteProfiles, 'listings.sites.detail');

export const fetchListingTemplates = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/listings/templates/' }, mockListingTemplates, 'listings.templates');
