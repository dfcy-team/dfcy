import { describe, expect, it } from 'vitest';
import { extractPermissionReferences, partitionPermissionReferences } from '../scripts/export-authorization-surface.mjs';

describe('authorization surface extraction', () => {
  it('captures permission checks and permission config literals', () => {
    const source = `
      auth.hasPermission('reports.view');
      hasActionPermission('reports.export');
      hasFieldPermission('field.customer.email.view');
      hasAllDataScopeFor('reports.view');
      usePermissionAccess('alerts.manage');
      const action = { permission: 'orders.approve' };
      <ResourcePage permission="masterdata.manage" />;
    `;
    expect(extractPermissionReferences(source)).toEqual([
      'alerts.manage', 'field.customer.email.view', 'masterdata.manage',
      'orders.approve', 'reports.export', 'reports.view'
    ]);
  });

  it('ignores API and mock tracing strings outside permission checks', () => {
    const source = `
      api.get('/orders.trace.fetch');
      const mock = { request_key: 'mock.permission.lookup' };
      auth.hasPermission('unknown.orders.manage');
    `;
    expect(extractPermissionReferences(source)).toEqual(['unknown.orders.manage']);
  });

  it('classifies an actual unknown permission check as a CI error candidate', () => {
    const rows = extractPermissionReferences(`auth.hasPermission('orders.not_registered')`)
      .map(permission_code => ({ file: 'src/example.js', permission_code }));
    expect(partitionPermissionReferences(rows, ['orders.view']).unknown).toEqual(rows);
  });
});
