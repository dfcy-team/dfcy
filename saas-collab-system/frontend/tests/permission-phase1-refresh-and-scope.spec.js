import { describe, expect, it } from 'vitest';
import { hasPlatformDetailScopeConflict } from '../src/utils/roleScopeCompatibility';

describe('第一阶段权限刷新与范围适配', () => {
  it('平台明细按平台、站点或店铺适配，仓库/供应商限制冲突时提示', () => {
    const codes = ['listings.product_detail.view'];
    expect(hasPlatformDetailScopeConflict(codes, { warehouse_ids: [7] })).toBe(true);
    expect(hasPlatformDetailScopeConflict(codes, { supplier_ids: [3] })).toBe(true);
    expect(hasPlatformDetailScopeConflict(codes, { platform_ids: [2], warehouse_ids: [7] })).toBe(true);
    expect(hasPlatformDetailScopeConflict(codes, { site_ids: [4], supplier_ids: [3] })).toBe(true);
    expect(hasPlatformDetailScopeConflict(codes, { store_ids: [9] })).toBe(false);
  });

  it('仓库适配权限仍可使用仓库范围，供应商范围也不被平台明细规则误判', () => {
    expect(hasPlatformDetailScopeConflict(['alerts.view'], { warehouse_ids: [7] })).toBe(false);
    expect(hasPlatformDetailScopeConflict(['suppliers.view'], { supplier_ids: [3] })).toBe(false);
  });

});
