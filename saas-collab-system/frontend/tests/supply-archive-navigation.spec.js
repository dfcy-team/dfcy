import {describe,it,expect} from 'vitest';
import {canAccessPath,filterMenuItems,menuItems} from '../src/router/menu';
import {buildMenuPermissionRegistry} from '../src/router/menuRegistry';

const supplierMenu='menu.supply.supply_archive_suppliers.view';
const user={user_type:'internal',permissions:[],action_permission_codes:[],menu_permission_codes:[supplierMenu]};

describe('supply archives in master data',()=>{
  it('keeps a single supplier entry and places all three archives in master data',()=>{
    const base=menuItems.find(item=>item.label==='基础档案');
    expect(base.children.filter(item=>item.path==='/master-data/suppliers')).toHaveLength(1);
    expect(base.children.map(item=>item.path)).toEqual(expect.arrayContaining(['/master-data/suppliers','/master-data/supplier-prices','/master-data/freight-companies']));
    const supply=menuItems.find(item=>item.label==='供应链协同');
    expect(supply.children.find(item=>item.path==='/supply-chain/costs').label).toBe('费用与结算');
  });
  it('does not turn the supply-only supplier menu into general master-data access',()=>{
    const registry=buildMenuPermissionRegistry(menuItems);
    expect(registry.find(row=>row.code===supplierMenu).metadata.action_codes).toEqual(['supply.v2.view']);
    expect(registry.find(row=>row.code==='menu.masterdata.master_data_suppliers.view').metadata.action_codes).toEqual(['masterdata.view']);
    expect(canAccessPath(user,'/master-data/suppliers')).toBe(true);
    expect(canAccessPath(user,'/master-data/warehouses')).toBe(false);
    expect(canAccessPath({...user,user_type:'external'},'/master-data/suppliers')).toBe(false);
    expect(filterMenuItems(user).find(item=>item.label==='基础档案').children.map(item=>item.path)).toEqual(['/master-data/suppliers']);
  });
  it('reuses the warehouse route while keeping supply and master-data action gates separate',()=>{
    const registry=buildMenuPermissionRegistry(menuItems),code='menu.supply.supply_archive_warehouses.view';
    expect(registry.find(row=>row.code===code).metadata.action_codes).toEqual(['supply.v2.view']);
    expect(registry.find(row=>row.code==='menu.masterdata.master_data_warehouses.view').metadata.action_codes).toEqual(['masterdata.view']);
    const buyer={...user,menu_permission_codes:[code]};
    expect(canAccessPath(buyer,'/master-data/warehouses')).toBe(true);
    expect(canAccessPath(buyer,'/master-data/stores')).toBe(false);
    expect(canAccessPath({...buyer,user_type:'external'},'/master-data/warehouses')).toBe(false);
    expect(menuItems.find(item=>item.label==='基础档案').children.filter(item=>item.path==='/master-data/warehouses')).toHaveLength(1);
  });
});
