import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { salesPageContracts } from '../src/views/sales-management/pageContracts';
import { salesManagementMocks } from '../src/mock/salesManagement';
import { fetchSalesPage } from '../src/api/salesManagement';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('sales management incremental integration', () => {
  it('keeps the seven existing route components while sharing the real-data workspace', () => {
    const routes = {
      SalesOverview: 'overview',
      SalesOrderList: 'orders',
      SalesReturnList: 'returns',
      StoreSalesList: 'stores',
      SkuSalesList: 'skus',
      SalesExportList: 'exports',
      SalesDataQualityList: 'data-quality'
    };
    for (const [component, mode] of Object.entries(routes)) {
      const source = read(`src/views/sales-management/${component}.vue`);
      expect(source).toContain(`<SalesWorkspace mode="${mode}" />`);
      expect(source).toContain("import SalesWorkspace from './SalesWorkspace.vue';");
    }
  });

  it('has a contract and mock dataset for every existing sales page', () => {
    for (const mode of ['overview', 'orders', 'returns', 'stores', 'skus', 'exports', 'data-quality']) {
      expect(salesPageContracts[mode]).toBeTruthy();
      expect(salesPageContracts[mode].columns.length).toBeGreaterThan(0);
      expect(typeof salesManagementMocks[mode === 'returns' ? 'refunds' : mode]).toBe('function');
    }
  });

  it('keeps the handoff filter and table dimensions on the six data pages', () => {
    for (const mode of ['overview', 'orders', 'returns', 'stores', 'skus', 'data-quality']) {
      expect(salesPageContracts[mode].filters.map((filter) => filter.key)).toEqual([
        'date_from', 'date_to', 'platform', 'store_id', 'currency'
      ]);
    }
    const workspace = read('src/views/sales-management/SalesWorkspace.vue');
    expect(workspace).toContain('SaaS MySQL 已更新');
    expect(workspace).toContain('按日销售趋势');
    expect(workspace).toContain('从已查询数据生成文件');
    expect(salesPageContracts['data-quality'].tableTitle).toBe('数据同步状态');
  });

  it('uses additive commerce and sales-management endpoints without touching menu or router source', () => {
    const api = read('src/api/salesManagement.js');
    expect(api).toContain("'/api/internal/commerce/overview/'");
    expect(api).toContain("'/api/internal/commerce/refunds/'");
    expect(api).toContain("'/api/internal/sales-management/exports/'");
    expect(api).toContain("requestWithMockFallback");
    expect(read('src/router/menu.js')).not.toContain('SalesWorkspace');
    expect(read('src/router/index.js')).not.toContain('SalesWorkspace');
  });

  it('keeps mock fallback payloads aligned with every page mode', async () => {
    const overview = await fetchSalesPage('overview');
    const returns = await fetchSalesPage('returns');
    const skus = await fetchSalesPage('skus');
    const exportsPage = await fetchSalesPage('exports');
    const quality = await fetchSalesPage('data-quality');
    expect(overview.data.results.length).toBeGreaterThan(0);
    expect(returns.data.results.length).toBeGreaterThan(0);
    expect(returns.data.results[0].external_return_id).toBeTruthy();
    expect(skus.data.results[0].internal_sku).toBeTruthy();
    expect(exportsPage.data.results.length).toBeGreaterThan(0);
    expect(quality.data.issues.length).toBeGreaterThan(0);
  });
});
