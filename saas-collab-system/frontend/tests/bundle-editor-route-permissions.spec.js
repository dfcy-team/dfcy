import { describe, expect, it } from 'vitest';
import { canAccessPath, findRouteCapability } from '../src/router/menu';

const path = '/products/bundles/9189/edit';
const retired = ['menu.products.products_bundles.view'];
const user = (overrides = {}) => ({
  user_type: 'internal', is_superuser: false,
  inactive_permission_codes: retired,
  menu_permission_codes: ['menu.products.products_details.view'],
  action_permission_codes: ['products.bundle.view', 'products.bundle.manage'],
  ...overrides,
});
describe('bundle editor after standalone menu retirement', () => {
  it('keeps the superuser editor reachable with the production retired menu metadata', () => {
    expect(canAccessPath(user({ is_superuser: true }), path)).toBe(true);
  });
  it('uses the existing product detail menu for the bundle editor', () => {
    expect(findRouteCapability(path).menuPermissions).toEqual(['menu.products.products_details.view']);
    expect(canAccessPath(user(), path)).toBe(true);
  });
  it('retains action restrictions for users without a corresponding menu or action grant', () => {
    expect(canAccessPath(user({menu_permission_codes: [], action_permission_codes: []}), path)).toBe(false);
  });
  it('keeps external users and disabled modules blocked', () => {
    expect(canAccessPath(user({user_type: 'external'}), path)).toBe(false);
    expect(canAccessPath(user({is_superuser:true,module_statuses:{masterdata:'disabled'}}), path)).toBe(false);
  });
  it('keeps retired bundle actions blocked', () => {
    expect(canAccessPath(user({inactive_permission_codes:[...retired,'products.bundle.view']}), path)).toBe(false);
  });
});
