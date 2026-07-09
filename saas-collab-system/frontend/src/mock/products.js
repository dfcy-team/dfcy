import { successResponse } from './index';

export const mockResearchList = () => successResponse({
  status: 'mock',
  module: 'products.research',
  items: [
    {
      id: 1,
      research_no: 'MOCK-RESEARCH-001',
      product_name: 'Mock Product',
      platform: 'mock-platform',
      competitor_url: 'https://example.invalid/mock-competitor',
      estimated_sales: 120,
      estimated_gross_margin: '0.3200',
      risk_points: ['mock-risk'],
      approval_status: 'pending',
      created_by_id: 1,
      created_at: '2026-07-09T00:00:00Z'
    }
  ]
});

export const mockResearchDetail = () => successResponse({
  status: 'mock',
  module: 'products.research.detail',
  id: 1,
  research_no: 'MOCK-RESEARCH-001',
  product_name: 'Mock Product',
  platform: 'mock-platform',
  competitor_url: 'https://example.invalid/mock-competitor',
  estimated_sales: 120,
  estimated_gross_margin: '0.3200',
  risk_points: ['mock-risk'],
  approval_status: 'pending',
  created_by_id: 1,
  created_at: '2026-07-09T00:00:00Z'
});

export const mockProductMasterList = () => successResponse({
  status: 'mock',
  module: 'products.master',
  items: [
    {
      id: 1,
      spu_code: 'MOCK-SPU-001',
      product_name: 'Mock Product',
      category: 'mock-category',
      lifecycle_status: 'draft',
      sales_status: 'not_listed',
      is_code_frozen: false
    }
  ]
});

export const mockProductMasterDetail = () => successResponse({
  status: 'mock',
  module: 'products.master.detail',
  id: 1,
  spu_code: 'MOCK-SPU-001',
  product_name: 'Mock Product',
  category: 'mock-category',
  lifecycle_status: 'draft',
  sales_status: 'not_listed',
  is_code_frozen: false
});

export const mockProductSkuList = () => successResponse({
  status: 'mock',
  module: 'products.skus',
  items: [
    {
      id: 1,
      spu: 1,
      sku_code: 'MOCK-SKU-001',
      size: 'mock-size',
      material: 'mock-material',
      selling_points: ['mock-selling-point'],
      package_weight: '0.500',
      package_volume: '0.020',
      is_code_frozen: false
    }
  ]
});

export const mockProductStatusList = () => successResponse({
  status: 'mock',
  module: 'products.status',
  items: [
    {
      id: 1,
      spu_code: 'MOCK-SPU-001',
      product_name: 'Mock Product',
      lifecycle_status: 'draft',
      sales_status: 'not_listed',
      is_code_frozen: false
    }
  ]
});

export const mockFreezeProductCode = () => successResponse({
  status: 'mock',
  module: 'products.master.freeze_code',
  id: 1,
  spu_code: 'MOCK-SPU-001',
  product_name: 'Mock Product',
  is_code_frozen: true
});
