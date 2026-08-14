import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const requestMock = vi.hoisted(() => vi.fn());

vi.mock('../src/api/request', () => ({ requestWithMockFallback: requestMock }));
vi.mock('../src/mock/salesManagement', () => ({ salesManagementMocks: {} }));

import {
  createSalesExport,
  requestSalesSyncRerun
} from '../src/api/salesManagement';
import { canAccessPath, filterMenuItems, flattenMenuItems, menuItems } from '../src/router/menu';
import { mockAuthUser } from '../src/mock/auth';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

const expectedRoutes = [
  '/sales-management/overview',
  '/sales-management/orders',
  '/sales-management/returns',
  '/sales-management/stores',
  '/sales-management/skus',
  '/sales-management/exports',
  '/sales-management/data-quality'
];

describe('sales management contracts', () => {
  beforeEach(() => requestMock.mockReset());

  it('keeps the fixed top-level and seven-page menu order', () => {
    const labels = menuItems.map((item) => item.label);
    expect(labels.indexOf('经营决策')).toBeLessThan(labels.indexOf('销售管理'));
    expect(labels.indexOf('销售管理')).toBeLessThan(labels.indexOf('达人管理'));
    expect(labels.indexOf('达人管理')).toBeLessThan(labels.indexOf('流程协同'));
    const sales = menuItems.find((item) => item.label === '销售管理');
    expect(sales.children.map((item) => item.path)).toEqual(expectedRoutes);
  });

  it('registers every route and denies missing or external capabilities', () => {
    const router = read('src/router/index.js');
    expectedRoutes.forEach((path) => expect(router).toContain(`path: '${path.slice(1)}'`));
    const orderViewer = { user_type: 'internal', permissions: ['sales_management.orders.view'] };
    const visible = flattenMenuItems(filterMenuItems(orderViewer))
      .map((item) => item.path)
      .filter((path) => path.startsWith('/sales-management/'));
    expect(visible).toEqual(['/sales-management/orders']);
    expect(canAccessPath(orderViewer, '/sales-management/orders')).toBe(true);
    expect(canAccessPath(orderViewer, '/sales-management/returns')).toBe(false);
    expect(canAccessPath({ ...orderViewer, user_type: 'external' }, '/sales-management/orders')).toBe(false);
    expectedRoutes.forEach((path) => expect(canAccessPath(mockAuthUser, path)).toBe(true));
    expect(mockAuthUser.permissions).toContain('sales_management.sync.rerun');
  });

  it('defines all page states, fixed filters, provenance and read-only boundaries', () => {
    const contracts = read('src/views/sales-management/pageContracts.js');
    const workspace = read('src/views/sales-management/SalesWorkspace.vue');
    for (const term of ['销售总览', '销售订单', '退款退货', '门店销售', 'SKU 销售', '销售明细导出', '数据同步与质量']) {
      expect(contracts).toContain(term);
    }
    for (const state of ['loading', 'empty', 'error', 'pending', 'stale', 'partial']) {
      expect(workspace).toContain(state);
    }
    expect(workspace).toContain('数据新鲜度与来源');
    expect(workspace).toContain('只读分析');
    expect(workspace).not.toContain('执行退款');
    expect(workspace).not.toContain('修改库存');
    expect(workspace).toContain("permissions.value.has('sales_management.sync.rerun')");
    expect(workspace).not.toContain("permissions.value.has('sales_management.sync.view')");
  });

  it('uses exact API routes and idempotency keys for controlled actions', () => {
    requestMock.mockReturnValue({ success: true, data: {} });
    createSalesExport({ export_type: 'orders', filters: {} }, 'export-key');
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/sales-management/exports/',
      headers: { 'Idempotency-Key': 'export-key' }
    });
    requestSalesSyncRerun({ sync_source_id: 7, reason: 'retry' }, 'rerun-key');
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/sales-management/sync-reruns/',
      headers: { 'Idempotency-Key': 'rerun-key' }
    });
  });

  it('never places credential material in frontend sales payloads', () => {
    const source = `${read('src/api/salesManagement.js')}\n${read('src/mock/salesManagement.js')}`.toLowerCase();
    expect(source).not.toContain('app_secret');
    expect(source).not.toContain('access_token');
    expect(source).not.toContain('refresh_token');
  });
});
