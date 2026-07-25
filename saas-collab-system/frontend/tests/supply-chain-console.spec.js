import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';

import { canAccessPath } from '../src/router/menu';
import {
  mockCreateSupplyOrder,
  mockFetchSupplyOrder,
  mockFetchSupplyOrders,
  mockRunSupplyOrderAction,
  resetMockSupplyOrders
} from '../src/mock/supplyChain';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('SC-F1 supply purchase order console', () => {
  beforeEach(() => {
    resetMockSupplyOrders();
  });

  it('registers an internal route with the exact view permission', () => {
    expect(canAccessPath(
      { user_type: 'internal', permissions: ['supply.purchase_order.view'] },
      '/supply-chain/purchase-orders'
    )).toBe(true);
    expect(canAccessPath(
      { user_type: 'internal', permissions: [] },
      '/supply-chain/purchase-orders'
    )).toBe(false);
    expect(canAccessPath(
      { user_type: 'external', permissions: ['supply.purchase_order.view'] },
      '/supply-chain/purchase-orders'
    )).toBe(false);
  });

  it('uses only controlled Django endpoints and idempotent action requests', () => {
    const api = read('src/api/supplyChain.js');
    expect(api).toContain('/api/internal/purchasing/supply-orders/');
    expect(api).toContain("'Idempotency-Key'");
    expect(api).not.toMatch(/supabase|service.?role|api\.weixin|jscode2session|mysql/i);
  });

  it('keeps the local-only and no-production boundary visible', () => {
    const page = read('src/views/purchasing/SupplyPurchaseOrderConsole.vue');
    expect(page).toContain('仅用于架构员主机');
    expect(page).toContain('不连接线上 Supabase');
    expect(page).toContain('不迁移生产数据');
    expect(page).toContain('不发送真实通知');
  });

  it('supports the first local header-line and production workflow in mock mode', () => {
    const created = mockCreateSupplyOrder({
      order_no: 'SC-TEST-001',
      supplier_id: 101,
      order_date: '2026-07-25',
      expected_delivery_date: '2026-08-25',
      currency: 'CNY',
      lines: [{ line_no: 1, sku_id: 201, quantity: 20, unit_price: '1.0000' }]
    }).data;
    expect(created.status).toBe('pending');
    expect(created.total_quantity).toBe(20);

    expect(mockRunSupplyOrderAction(created.id, 'accept').data.order.status).toBe('accepted');
    expect(mockRunSupplyOrderAction(created.id, 'start-production').data.order.status).toBe('in_production');
    expect(mockRunSupplyOrderAction(
      created.id,
      'update-progress',
      { completed_quantity: 20 }
    ).data.order.completed_quantity).toBe(20);
    expect(mockRunSupplyOrderAction(
      created.id,
      'complete-production'
    ).data.order.status).toBe('production_completed');
    expect(mockFetchSupplyOrder(created.id).data.events).toHaveLength(4);
    expect(mockFetchSupplyOrders({ search: 'SC-TEST-001' }).data.count).toBe(1);
  });

  it('passes backend pagination and paginates mock results consistently', () => {
    const page = read('src/views/purchasing/SupplyPurchaseOrderConsole.vue');
    expect(page).toContain('<el-pagination');
    expect(page).toContain('page_size: pagination.pageSize');

    for (const orderNo of ['SC-PAGE-001', 'SC-PAGE-002']) {
      mockCreateSupplyOrder({
        order_no: orderNo,
        supplier_id: 101,
        order_date: '2026-07-25',
        expected_delivery_date: '2026-08-25',
        currency: 'CNY',
        lines: [{ line_no: 1, sku_id: 201, quantity: 1, unit_price: '1.0000' }]
      });
    }
    const first = mockFetchSupplyOrders({ page: 1, page_size: 1 }).data;
    const second = mockFetchSupplyOrders({ page: 2, page_size: 1 }).data;
    expect(first.count).toBe(3);
    expect(first.results).toHaveLength(1);
    expect(second.results).toHaveLength(1);
    expect(second.results[0].id).not.toBe(first.results[0].id);
  });
});
