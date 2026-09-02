import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { collectionRows, collectionTotal, detailData } from '../src/utils/businessResponse';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('UI-P5 business response contract', () => {
  it('parses connected pagination and mock item envelopes', () => {
    expect(collectionRows({ count: 1, results: [{ id: 1 }] })).toEqual([{ id: 1 }]);
    expect(collectionRows({ status: 'mock', items: [{ id: 2 }] })).toEqual([{ id: 2 }]);
    expect(collectionTotal({ count: 12, results: [] })).toBe(12);
    expect(detailData({ items: [{ id: 3 }] })).toEqual({ id: 3 });
  });
});

describe('UI-P5 API and permission boundaries', () => {
  it('uses declared permissions for product and purchasing routes', () => {
    const menu = read('src/router/menu.js');
    expect(menu).toContain("permissions: ['products.research.view']");
    expect(menu).toContain("permissions: ['products.master.view']");
    expect(menu).toContain("permissions: ['purchasing.orders.view']");
  });

  it('uses PATCH for supplier feedback and never accepts supplier_id from the page', () => {
    const api = read('src/api/suppliers.js');
    const page = read('src/views/suppliers/SupplierTaskDetail.vue');
    expect(api).toContain("method: 'patch'");
    expect(page).not.toContain('supplier_id:');
  });

  it('does not request nonexistent listing and pricing endpoints', () => {
    const listings = read('src/api/listings.js');
    const pricing = read('src/api/pricing.js');
    expect(listings).toContain('requestPendingOrMock');
    expect(pricing).toContain('requestPendingOrMock');
    expect(listings).not.toContain('/api/internal/listings/');
    expect(pricing).not.toContain('/api/internal/pricing/');
  });

  it('keeps listing, repricing and automatic procurement actions disabled', () => {
    const pending = read('src/views/_ControlledPendingPage.vue');
    const listing = read('src/views/listings/SiteProfileList.vue');
    const pricing = read('src/views/pricing/PriceList.vue');
    const purchase = read('src/views/purchasing/PurchaseOrderList.vue');
    expect(pending).toMatch(/<el-button\s+v-for="action in actions"[^>]+disabled>/);
    expect(listing).toContain('生成 RPA 任务（禁用）');
    expect(pricing).toContain('提交价格审批（禁用）');
    expect(purchase).toContain('不自动采购');
  });
});
