import { successResponse } from './index';

export const mockAuthUser = {
  user_id: 'mock-user-001',
  username: 'stage0_internal_user',
  user_type: 'internal',
  tenant_id: 'mock-tenant-001',
  is_superuser: false,
  roles: ['stage0_viewer'],
  permissions: [
    'mock.view',
    'system.organization.view', 'system.organization.manage',
    'system.users.view', 'system.users.manage',
    'system.roles.view', 'system.roles.manage',
    'masterdata.view', 'masterdata.manage',
    'security.operations.view',
    'products.research.view', 'products.research.manage',
    'products.master.view', 'products.master.manage', 'products.master.freeze',
    'purchasing.orders.view', 'purchasing.orders.manage',
    'rpa.tasks.view', 'rpa.tasks.manage',
    'rpa.devices.view', 'rpa.devices.dry_run',
    'rpa.stability.view',
    'workflow.approvals.view', 'workflow.approvals.submit', 'workflow.approvals.review', 'workflow.approvals.withdraw',
    'workflow.exceptions.view', 'workflow.exceptions.manage',
    'workflow.collaboration.view', 'workflow.collaboration.confirm',
    'reports.view', 'reports.export', 'reports.download'
  ],
  data_scope: []
};

export const mockLogin = () => successResponse({
  status: 'mock',
  session: 'mock-session-only',
  user: mockAuthUser
});

export const mockCurrentUser = () => successResponse(mockAuthUser);
