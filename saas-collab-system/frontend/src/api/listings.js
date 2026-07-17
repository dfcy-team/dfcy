import { requestPendingOrMock } from './request';
import { mockListingTemplates, mockSiteProfiles } from '../mock/listings';

export const fetchSiteProfiles = () =>
  requestPendingOrMock(mockSiteProfiles, 'listings.sites');

export const fetchSiteProfileDetail = (id = 1) =>
  requestPendingOrMock(mockSiteProfiles, `listings.sites.detail:${id}`);

export const fetchListingTemplates = () =>
  requestPendingOrMock(mockListingTemplates, 'listings.templates');
