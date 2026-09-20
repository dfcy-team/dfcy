import { successResponse } from './index';

const researchItem = {
  id: 1,
  research_no: 'MOCK-RESEARCH-001',
  product_name: 'Mock Product',
  platform: 'mock-platform',
  competitor_url: 'https://example.invalid/mock-competitor',
  estimated_sales: 120,
  estimated_gross_margin: '0.3200',
  risk_points: ['mock-risk'],
  approval_status: 'pending'
};

const spuItem = {
  id: 1,
  spu_code: 'MOCK-SPU-001',
  product_name: 'Mock Product',
  category: 'mock-category',
  category_node: 3,
  lifecycle_status: 'draft',
  sales_status: 'not_listed',
  is_code_frozen: false,
  product_type: 'standard'
};

const bundleSpuItem = {
  id: 2,
  spu_code: 'MOCK-BUNDLE-SPU-001',
  legacy_spu_code: 'ZH-DEMO-001',
  product_name: '演示组合商品',
  category: 'mock-category',
  lifecycle_status: 'draft',
  sales_status: 'not_listed',
  is_code_frozen: false,
  product_type: 'bundle'
};

const skuItem = {
  id: 1,
  spu: 1,
  sku_code: 'MOCK-SKU-001',
  size: 'mock-size',
  material: 'mock-material',
  selling_points: ['mock-selling-point'],
  package_weight: '0.500',
  package_volume: '0.020',
  is_code_frozen: false
};

const bundleSkuItem = {
  id: 2,
  spu: 2,
  sku_code: 'MOCK-BUNDLE-SKU-001',
  legacy_sku_code: 'ZH-DEMO-001-WHITE',
  product_name: '演示组合商品',
  is_code_frozen: false
};

export const mockResearchList = () => successResponse({
  status: 'mock',
  module: 'products.research',
  items: [researchItem]
});

export const mockResearchDetail = () => successResponse({
  status: 'mock',
  module: 'products.research.detail',
  ...researchItem
});

export const mockProductMasterList = () => successResponse({
  status: 'mock',
  module: 'products.spus',
  items: [spuItem, bundleSpuItem]
});

export const mockProductMasterDetail = () => successResponse({
  status: 'mock',
  module: 'products.spus.detail',
  ...spuItem
});

export const mockProductSkuList = () => successResponse({
  status: 'mock',
  module: 'products.skus',
  items: [skuItem, bundleSkuItem]
});

export const mockProductDetailList = () => successResponse({
  status: 'mock',
  module: 'products.details',
  items: [],
});

export const mockProductStatusList = () => successResponse({
  status: 'mock',
  module: 'products.status',
  items: [spuItem]
});

export const mockFreezeProductCode = () => successResponse({
  status: 'mock',
  module: 'products.spus.freeze_code',
  ...spuItem,
  is_code_frozen: true
});
