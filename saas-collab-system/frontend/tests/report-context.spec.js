import { describe, expect, it } from 'vitest';
import { accessFailure, defaultReportFilters, queryScope, reportQuality, reportResponseError, reportScopeNote, reportUnitLabel } from '../src/views/reports/reportContext';
import { widgetDisplayTitle, dashboardTemplate } from '../src/views/reports/biDashboard';

describe('报表口径与数据质量', () => {
  it('separates advertising and quantity-only inventory explanations from financial scope', () => {
    expect(reportScopeNote('advertising')).toContain('来源广告报表日期');
    expect(reportScopeNote('advertising')).not.toMatch(/流水|利润|协调世界时/);
    expect(reportScopeNote('finance')).toContain('净流水不是利润');
    expect(queryScope({ dataset: 'inventory', filters: { site_code: 'PH', date_to: '2026-10-22' } }).join(' ')).not.toMatch(/金额|币种/);
    expect(reportUnitLabel('inventory')).not.toMatch(/金额|原币/);
    expect(queryScope({ dataset: 'inventory_value' })).toContain('金额按成本币种分组');
  });
  it('renders SKU grouping and sorting without exposing transport flags or mutating applied filters', () => {
    const filters = { report: 'true', grouping: 'store', ordering: '-gross_sales', include_summary: 'false', exclude_cancelled: true, sku: '旧-A' };
    const before = JSON.stringify(filters);
    const scope = queryScope({ dataset: 'sales', filters }).join(' ');
    expect(scope).toContain('汇总方式：店铺商品编码');
    expect(scope).toContain('结果排序：非取消订单销售额 · 降序');
    expect(scope).toContain('排除取消订单：是');
    expect(scope).not.toMatch(/true|false|store|gross_sales|业务条件/);
    expect(queryScope({ dataset: 'sales', filters: { grouping: 'product' } }).join(' ')).toContain('内部商品编码');
    expect(JSON.stringify(filters)).toBe(before);
    expect(queryScope({ dataset: 'sales_skus', filters }).join(' ')).toContain('非取消商品销售额 · 降序');
    expect(queryScope({ dataset: 'sales_skus', filters: { sku: 'true' } }).join(' ')).toContain('商品编码（新/旧/别名）：true');
    expect(queryScope({ dataset: 'sales_skus', filters: { unmapped_only: true } })).toContain('商品关联状态：仅未关联商品');
    expect(queryScope({ dataset: 'sales_skus', filters: { unmapped_only: false } })).toContain('商品关联状态：全部商品');
    expect(queryScope({ dataset: 'inventory', filters: { unmapped_only: 'true' } })).toContain('商品关联状态：仅未关联商品');
    expect(queryScope({ dataset: 'inventory', filters: { unmapped_only: 'false' } })).toContain('商品关联状态：全部商品');
  });
  it('aligns the advertising preset title with dates while preserving custom and store titles', () => {
    const widget = { title: '店铺广告消耗（原币）', config: { dataset: 'advertising', dimensions: ['date', 'currency'] } };
    expect(widgetDisplayTitle(widget)).toBe('每日广告消耗（原币）');
    expect(widget.title).toBe('店铺广告消耗（原币）');
    expect(widgetDisplayTitle({ ...widget, title: '我的广告观察' })).toBe('我的广告观察');
    expect(widgetDisplayTitle({ ...widget, config: { ...widget.config, dimensions: ['store_id', 'currency'] } })).toBe(widget.title);
    const dataset = { id: 'advertising', name: '广告', defaults: { dimensions: ['date', 'currency'], metrics: ['expense'] }, dimensions: [{ key: 'date' }, { key: 'currency' }], metrics: [{ key: 'expense' }], filters: [] };
    expect(dashboardTemplate('经营分析', [dataset]).widgets[0].title).toBe('每日广告消耗（原币）');
  });
  it('shows selected store names without changing stored filter IDs', () => {
    const config = { dataset: 'sales', filters: { store_ids: '42,43' } };
    expect(queryScope(config, { store_id: { 42: '菲律宾运营店' } }).join(' ')).toContain('菲律宾运营店（42）、43');
    expect(config.filters.store_ids).toBe('42,43');
  });
  it('uses bounded defaults without inventing unsupported filters', () => {
    expect(defaultReportFilters({ id: 'finance', filters: ['date_from', 'date_to'] }, new Date('2026-10-03T08:00:00Z'))).toEqual({ date_from: '2026-10-01', date_to: '2026-10-03' });
    expect(defaultReportFilters({ id: 'inventory', filters: ['warehouse_id'] })).toEqual({});
  });
  it('preserves literal SKU codes and explicitly states virtual and currency scope', () => {
    expect(queryScope({ dataset: 'inventory_value', filters: { sku: ' 旧-A ', sku_mode: 'related' } }).join(' ')).toContain(' 旧-A ');
    expect(queryScope({ dataset: 'inventory_value' })).toEqual(expect.arrayContaining(['排除虚拟商品', '金额按成本币种分组']));
  });
  it('does not turn unavailable, empty-denominator or truncated quality into complete totals', () => {
    const config = { metrics: ['sku_count', 'valued_count', 'missing_cost_count'] };
    const cards = reportQuality({ config, rows: [{ sku_count: 0, valued_count: 0, missing_cost_count: 0 }] }, 'inventory_value');
    expect(cards[0].value).toBe('—'); expect(cards[2].value).toBe('未提供');
    expect(reportQuality({ config, rows: [], truncated: true }, 'inventory_value')).toEqual([]);
  });
  it('counts records rather than summing cross-currency amounts', () => {
    const config = { metrics: ['transaction_count', 'unknown_count', 'unmatched_count'] };
    const cards = reportQuality({ config, rows: [{ transaction_count: 7, unknown_count: 4, unmatched_count: 1 }, { transaction_count: 3, unknown_count: 2, unmatched_count: 1 }] }, 'finance');
    expect(cards[0].value).toBe('10'); expect(cards[1].note).toContain('60.0%'); expect(cards[2].label).toContain('冲突');
  });
  it('keeps the HTTP authorization status even when the response message is generic', () => {
    expect(accessFailure(reportResponseError({ http_status: 403, message: '请求错误' }))).toBe(true);
    expect(accessFailure(reportResponseError({ http_status: 504, message: '请求错误' }))).toBe(false);
  });
});
