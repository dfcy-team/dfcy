import { getMockResponse } from './request';
import { mockListingTemplates, mockSiteProfiles } from '../mock/listings';

export const fetchSiteProfiles = () => getMockResponse(mockSiteProfiles, 'listings.sites');
export const fetchListingTemplates = () => getMockResponse(mockListingTemplates, 'listings.templates');
