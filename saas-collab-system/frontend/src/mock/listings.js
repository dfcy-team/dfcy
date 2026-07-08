import { successResponse } from './index';

export const mockSiteProfiles = () => successResponse({
  status: 'mock',
  module: 'listings.sites',
  items: [
    {
      sku: 'MOCK-SKU-001',
      platform: 'mock-platform',
      country: 'mock-country',
      listing_status: 'draft'
    }
  ]
});

export const mockListingTemplates = () => successResponse({
  status: 'mock',
  module: 'listings.templates',
  items: [
    {
      template_no: 'MOCK-TEMPLATE-001',
      platform: 'mock-platform',
      country: 'mock-country'
    }
  ]
});
