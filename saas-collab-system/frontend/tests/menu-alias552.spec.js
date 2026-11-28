import { describe, expect, it } from 'vitest';
import { buildMenuPermissionRegistry } from '../src/router/menuRegistry';
import { menuItems, canAccessPath, filterMenuItems, filterSidebarMenuItems, flattenMenuItems } from '../src/router/menu';

const canonical = { path: '/costs', label: 'Costs', menuPermissions: ['menu.products.costs.view'], permissions: ['products.cost.view'] };
const alias = { ...canonical, path: '/inventory/costs', menuAlias: '/costs', label: 'Ledger' };

describe('explicit menu aliases preserve grants without registry collisions', () => {
  it('keeps one canonical definition while both routes retain the same access', () => {
    expect(buildMenuPermissionRegistry([canonical, alias])).toHaveLength(1);
    const registry = buildMenuPermissionRegistry(menuItems);
    expect(registry.some((item) => item.metadata.registry_collision)).toBe(false);
    expect(registry.find((item) => item.code === 'menu.products.products_costs.view').metadata.path).toBe('/products/costs');
    const user = { user_type: 'internal', menu_permission_codes: ['menu.products.products_costs.view'], action_permission_codes: ['products.cost.view'], permissions: [] };
    expect(canAccessPath(user, '/inventory/cost-ledger')).toBe(true);
    expect(canAccessPath(user, '/products/costs')).toBe(true);
    expect(flattenMenuItems(filterMenuItems(user)).some((item) => item.path === '/inventory/cost-ledger')).toBe(true);
    user.action_permission_codes = [];
    expect(canAccessPath(user, '/inventory/cost-ledger')).toBe(canAccessPath(user, '/products/costs'));
    user.menu_permission_codes = [];
    expect(canAccessPath(user, '/inventory/cost-ledger')).toBe(false);
  });
  it('rejects missing or ambiguous canonical routes, altered grants and action scopes', () => {
    for (const entry of [
      { ...alias, menuAlias: '/missing' },
      { ...alias, menuPermissions: ['menu.other.view'] },
      { ...alias, permissions: ['finance.view'] },
      { ...alias, allPermissions: ['finance.view'] },
      { ...alias, superuserOnly: true },
      { ...alias, menuActionPermissions: { 'menu.products.costs.view': ['finance.view'] } },
    ]) expect(() => buildMenuPermissionRegistry([canonical, entry])).toThrow();
    expect(() => buildMenuPermissionRegistry([canonical, { ...canonical }, alias])).toThrow();
  });
  it('continues to flag ordinary duplicate-code collisions', () => {
    const rows = buildMenuPermissionRegistry([canonical, { ...alias, menuAlias: undefined }]);
    expect(rows[0].metadata.registry_collision).toBe(true);
  });
});

const oldCode = 'menu.products.products_costs.view';
const ledgerCode = 'menu.products.inventory_cost_ledger.view';
describe('ledger permission revision preserves existing role access', () => {
  it.each([
    ['old', [oldCode], [], [], true, true, true],
    ['new', [ledgerCode], [], [], true, true, false],
    ['both', [oldCode, ledgerCode], [], [], true, true, true],
    ['none', [], [], [], false, false, false],
    ['new hidden', [oldCode, ledgerCode], [ledgerCode], [], false, true, true],
    ['new inactive', [oldCode, ledgerCode], [], [ledgerCode], false, false, true],
  ])('%s', (_name, grants, hidden, inactive, sidebar, ledger, costs) => {
    const user = { user_type: 'internal', menu_permission_codes: grants, action_permission_codes: [], permissions: [], hidden_menu_permission_codes: hidden, inactive_permission_codes: inactive };
    expect(flattenMenuItems(filterSidebarMenuItems(user)).some(item => item.path === '/inventory/cost-ledger')).toBe(sidebar);
    expect(canAccessPath(user, '/inventory/cost-ledger')).toBe(ledger);
    expect(canAccessPath(user, '/products/costs')).toBe(costs);
  });
  it('preserves legacy union action access', () => {
    const user = { user_type: 'internal', permissions: [ledgerCode, 'products.cost.view'] };
    expect(canAccessPath(user, '/inventory/cost-ledger')).toBe(true);
    expect(canAccessPath(user, '/products/costs')).toBe(true);
    user.permissions = [oldCode, 'products.cost.view'];
    expect(canAccessPath(user, '/inventory/cost-ledger')).toBe(true);
  });
});