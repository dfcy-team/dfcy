import { describe, expect, it } from 'vitest';
import { buildMenuPermissionRegistry } from '../src/router/menuRegistry.js';
import { canAccessMenuItem, canAccessPath, filterSidebarMenuItems, flattenMenuItems, menuItems, menuPermissionRegistry } from '../src/router/menu.js';

const path = '/sales/pre-shipment-adjustments';
const code = 'menu.sales_management.sales_pre_shipment_adjustments.view';
const entry = flattenMenuItems(menuItems).find(row => row.path === path);

describe('cloud exchange menu retirement preservation', () => {
  it('keeps the stable code and declares its persisted inactive lifecycle', () => {
    const definition = menuPermissionRegistry.find(row => row.code === code);
    expect(definition.metadata).toMatchObject({ path, status: 'inactive', registry_status: 'inactive', registry_source: 'frontend/src/router/menu.js' });
    expect(menuPermissionRegistry.filter(row => row.metadata.status !== 'active').map(row => row.code)).toEqual([code]);
  });

  it.each([
    { user_type: 'internal', is_superuser: true },
    { user_type: 'internal', permissions: [code, 'sales_management.exchange.view'] },
    { user_type: 'internal', menu_permission_codes: [code], action_permission_codes: ['sales_management.exchange.view'] },
  ])('denies sidebar and deep links even with cached grants or superuser bypass: %o', (user) => {
    expect(canAccessMenuItem(user, entry)).toBe(false);
    expect(canAccessPath(user, path)).toBe(false);
    expect(flattenMenuItems(filterSidebarMenuItems(user)).some(row => row.path === path)).toBe(false);
  });

  it('retains active default semantics and rejects invalid lifecycle declarations', () => {
    const active = { ...entry, menuPermissionStatus: undefined };
    expect(buildMenuPermissionRegistry([active])[0].metadata.status).toBe('active');
    expect(() => buildMenuPermissionRegistry([{ ...entry, menuPermissionStatus: 'enabled' }])).toThrow('Invalid menu permission lifecycle');
    const user = { user_type: 'internal', is_superuser: true };
    expect(canAccessPath(user, '/sales-management/orders')).toBe(true);
  });
});
