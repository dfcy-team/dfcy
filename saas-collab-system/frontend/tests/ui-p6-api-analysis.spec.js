import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  buildAnalyticsQuery,
  buildFinanceAnalyticsQuery,
  normalizeAnalyticsResponse
} from '../src/api/uiP6Adapters';
import { normalizeApiResponse, withApiStatus } from '../src/api/request';
import { mockAuthUser } from '../src/mock/auth';
import { canAccessPath } from '../src/router/menu';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('UI-P6 API and analytics contract', () => {
  it('limits Mock verification to read and Mock-safe UI-P6 permissions', () => {
    expect(mockAuthUser.permissions).toEqual(expect.arrayContaining([
      'analytics.view',
      'analytics.calculate',
      'finance.view',
      'products.lifecycle.view',
      'products.lifecycle.evaluate',
      'integrations.view',
      'integrations.manage',
      'integrations.run'
    ]));
    expect(mockAuthUser.permissions).not.toContain('products.lifecycle.high_risk_confirm');
    expect(mockAuthUser.permissions).not.toContain('finance.reconcile');
  });

  it('maps UI filters to the frozen analytics query contract', () => {
    expect(buildAnalyticsQuery({
      date_range: ['2026-07-01', '2026-07-31'],
      store: 'demo-store',
      warehouse: 'demo-warehouse',
      risk_level: 'high',
      page: 2,
      page_size: 20
    })).toEqual({
      period_start: '2026-07-01',
      period_end: '2026-07-31',
      store_id: 'demo-store',
      warehouse_id: 'demo-warehouse',
      page: 2,
      page_size: 20
    });
  });

  it('maps finance dates without adding forbidden query parameters', () => {
    expect(buildFinanceAnalyticsQuery({ date_range: ['2026-06-01', '2026-06-30'], currency: 'USD' }))
      .toEqual({ period_start: '2026-06-01', period_end: '2026-06-30', currency: 'USD' });
  });

  it('normalizes aggregate dimensions without reconstructing tenant scope', () => {
    const response = normalizeAnalyticsResponse({
      success: true,
      data: {
        quality: { status: 'good', metric_version: 'demo-v1', refreshed_at: '2026-07-17' },
        results: [{ id: 1, code: 'BI_SALES', label: 'Sales', value: 8, dimensions: { platform: 'demo', store_id: 'store-1' } }]
      }
    });
    expect(response.data.results[0]).toMatchObject({
      metric_code: 'BI_SALES',
      metric_name: 'Sales',
      metric_version: 'demo-v1',
      quality_status: 'good',
      updated_at: '2026-07-17',
      is_missing: false,
      platform: 'demo',
      store_id: 'store-1'
    });
    expect(response.data.results[0]).not.toHaveProperty('tenant_id');
  });

  it('registers the overview route under analytics.view and denies missing permission', () => {
    const viewer = { user_type: 'internal', permissions: ['analytics.view'] };
    const other = { user_type: 'internal', permissions: ['finance.view'] };
    expect(canAccessPath(viewer, '/analytics/overview')).toBe(true);
    expect(canAccessPath(other, '/analytics/overview')).toBe(false);
    expect(read('src/router/index.js')).toContain("path: 'analytics/overview'");
  });

  it('uses only the frozen paths and explicit degraded state', () => {
    const analytics = read('src/api/analytics.js');
    const finance = read('src/api/financeAnalytics.js');
    const request = read('src/api/request.js');
    expect(analytics).toContain('/api/internal/analytics/overview/');
    expect(analytics).toContain('/api/internal/analytics/sales/');
    expect(analytics).toContain('/api/internal/analytics/inventory/');
    expect(finance).toContain('/api/finance/analytics/overview/');
    expect(request).toContain("api_status: 'degraded'");
  });

  it('rejects malformed API envelopes without marking them connected', () => {
    const malformed = normalizeApiResponse({ legacy_payload: true });
    const result = withApiStatus(malformed, 'connected');

    expect(result).toMatchObject({
      success: false,
      code: 'INVALID_API_RESPONSE',
      data: null,
      protocol_error: true
    });
    expect(result).not.toHaveProperty('api_status');
  });

  it('renders contract fields, pagination and no finance fund actions', () => {
    const page = read('src/components/Phase3AnalyticsPage.vue');
    const finance = read('src/views/finance/FinanceAnalyticsOverview.vue');
    expect(page).toContain('<el-pagination');
    expect(finance).toContain("prop: 'statement_amount'");
    expect(finance).toContain("prop: 'account_mask'");
    expect(finance).not.toContain('<el-button');
    expect(finance).not.toMatch(/submitPayment|transferFunds|withdrawFunds/);
  });
});
