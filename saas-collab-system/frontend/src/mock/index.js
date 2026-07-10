export const mockCurrentUser = {
  user_id: 'mock-user-001',
  username: 'stage0_internal_user',
  user_type: 'internal',
  tenant_id: 'mock-tenant-001',
  roles: ['stage0_viewer'],
  permissions: ['mock.view'],
  data_scope: 'tenant'
};

export const successResponse = (data = {}) => ({
  success: true,
  code: 'OK',
  message: 'success',
  data
});

export const pendingResponse = (moduleName) => successResponse({
  status: 'pending',
  module: moduleName,
  items: []
});

export const rpaStatuses = [
  'pending',
  'claimed',
  'running',
  'success',
  'failed',
  'retrying',
  'manual_required',
  'cancelled'
];

export const rpaTaskTypes = [
  'BIGSELLER_CREATE_PRODUCT',
  'BIGSELLER_UPLOAD_IMAGES',
  'BIGSELLER_MULTI_SITE_LISTING',
  'BIGSELLER_UPDATE_PRICE',
  'BIGSELLER_READ_PAGE_PRICE',
  'BIGSELLER_COLLECT_LISTING_STATUS'
];
