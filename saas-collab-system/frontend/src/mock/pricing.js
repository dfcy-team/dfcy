import { successResponse } from './index';

export const mockPrices = () => successResponse({
  status: 'mock',
  module: 'pricing.prices',
  items: [
    {
      sku: 'MOCK-SKU-001',
      currency: 'USD',
      suggested_price: '0.00',
      approval_status: 'pending'
    }
  ]
});
