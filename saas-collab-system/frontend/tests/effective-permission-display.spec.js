import { describe, expect, it } from 'vitest';
import { effectivePermissionModule, effectivePermissionSourceLabels, filterEffectivePermissions, formatEffectivePermissionDetail, isInactiveEffectivePermission, paginateEffectivePermissions, annotateEffectivePermissionAvailability } from '../src/utils/effectivePermissionDisplay';

const records = [
  { code: 'menu.products', permission_type: 'menu', allowed: true, sources: [{ role_code: 'administrator' }, { role_code: 'administrator' }, { source: 'user' }] },
  { code: 'field.products.master.sku_code.view', permission_type: 'field', allowed: true, sources: [] },
  { code: 'sales.orders.export', permission_type: 'action', allowed: false, sources: [], is_active: false },
];

describe('effective permission display', () => {
  it('formats source scope arrays and does not mistake a field scope for unrestricted data', () => {
    const detail = (type, scope) => formatEffectivePermissionDetail({permission_type:type,sources:[{scope}]})[0].scope;
    expect(detail('action',[{scope_type:'all',config:{}}])).toBe('全部数据');
    expect(detail('action',[{scope_type:'custom',config:{warehouse_ids:[2,3]}}])).toBe('仓库：2、3');
    expect(detail('field',[])).toBe('随对应功能权限');
  });
  it('hides disabled-module grants by default while preserving shared active page grants and source details', () => {
    const source = {role_code:'administrator'};
    const rows = annotateEffectivePermissionAvailability([
      {code:'development.project.view',permission_type:'action',allowed:true,sources:[source]},
      {code:'listings.product_detail.view',permission_type:'action',allowed:true,sources:[source]},
    ], {product_development:'disabled',global_listing:'disabled',masterdata:'enabled'});
    expect(filterEffectivePermissions(rows).map(row=>row.code)).toEqual(['listings.product_detail.view']);
    expect(filterEffectivePermissions(rows,{showInactive:true})).toHaveLength(2);
    expect(rows[0]).toMatchObject({allowed:true,module_disabled:true,sources:[source]});
  });
  it('groups records into business modules and keeps employee readonly out of module rail', () => {
    expect(effectivePermissionModule({ code: 'menu.products.master' })).toBe('products');
    expect(effectivePermissionModule({ code: 'field.products.master.sku_code.view' })).toBe('products');
    expect(effectivePermissionModule({ code: 'employee_readonly.view' })).toBe('system');
  });

  it('filters by localized name or code, type, result, module, and explicit inactive state', () => {
    expect(filterEffectivePermissions(records, { query: '商品', type: 'menu' })).toHaveLength(1);
    expect(filterEffectivePermissions(records, { query: 'sku_code' })).toHaveLength(1);
    expect(filterEffectivePermissions(records, { result: 'denied' })).toHaveLength(0);
    expect(filterEffectivePermissions(records, { showInactive: true, result: 'denied' })).toHaveLength(1);
    expect(filterEffectivePermissions([{ code: 'sales.orders.view', allowed: true }])).toHaveLength(1);
    expect(isInactiveEffectivePermission({ status: 'retired' })).toBe(true);
  });

  it('deduplicates localized source labels while preserving each detail row and technical identifiers', () => {
    const roles = [{ id: 1, code: 'administrator', name: '系统管理员' }];
    expect(effectivePermissionSourceLabels(records[0], roles)).toEqual(['系统管理员', '用户指定']);
    expect(formatEffectivePermissionDetail(records[0], roles)).toHaveLength(3);
    expect(formatEffectivePermissionDetail(records[0], roles)[0].role).toBe('系统管理员');
  });

  it('paginates deterministically and clamps pages after filtering', () => {
    expect(paginateEffectivePermissions(records, 8, 2)).toMatchObject({ page: 2, pages: 2, total: 3 });
    expect(paginateEffectivePermissions(records, 1, 2).items).toHaveLength(2);
  });
});
