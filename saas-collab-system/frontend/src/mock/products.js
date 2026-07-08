import { successResponse } from './index';

export const mockResearchList = () => successResponse({
  status: 'mock',
  module: 'products.research',
  items: [
    {
      research_no: 'MOCK-RESEARCH-001',
      product_name: 'Mock Product',
      platform: 'mock-platform',
      approval_status: 'pending'
    }
  ]
});

export const mockProductMasterList = () => successResponse({
  status: 'mock',
  module: 'products.master',
  items: [
    {
      product_code: 'MOCK-PRODUCT-001',
      spu: 'MOCK-SPU-001',
      sku: 'MOCK-SKU-001',
      lifecycle_status: 'draft'
    }
  ]
});
