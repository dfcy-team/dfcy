import { successResponse } from './index';

export const mockAuthUser = {
  user_id: 'mock-user-001',
  username: 'stage0_internal_user',
  user_type: 'internal',
  tenant_id: 'mock-tenant-001',
  roles: ['stage0_viewer'],
  permissions: ['mock.view'],
  data_scope: 'tenant'
};

export const mockLogin = () => successResponse({
  status: 'mock',
  session: 'mock-session-only',
  user: mockAuthUser
});

export const mockCurrentUser = () => successResponse(mockAuthUser);
