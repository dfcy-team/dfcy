import { successResponse } from './index';

const page = (results) => ({ status: 'mock', count: results.length, next: null, previous: null, results });

export const masterDataMocks = {
  platforms: () => successResponse(page([
    { id: 1, tenant_id: 1, code: 'demo-marketplace', name: '示例平台', platform_type: 'other', status: 'active' }
  ])),
  stores: () => successResponse(page([
    {
      id: 1, tenant_id: 1, platform_id: 1, platform_name: '示例平台', code: 'demo-store-sg', name: '新加坡示例店铺',
      country_code: 'SG', currency: 'SGD', timezone: 'Asia/Singapore', status: 'active'
    }
  ])),
  warehouses: () => successResponse(page([
    { id: 1, tenant_id: 1, code: 'demo-wh-cn', name: '华南示例仓', country_code: 'CN', warehouse_type: 'owned', status: 'active' }
  ])),
  suppliers: () => successResponse(page([
    {
      id: 1, tenant_id: 1, code: 'demo-supplier', name: '示例供应商', contact_alias: '联系人A',
      contact_email_masked: 'd***@example.com', contact_phone_masked: '***8800', status: 'active'
    }
  ]))
};
