import { describe, expect, it } from 'vitest';
import { fieldLayout, moveField, removeField, matrixRows, chartData } from '../src/views/reports/biLayout';
import { dashboardTemplate, drillLocation, newWidget, queryWithLink, selectionLink } from '../src/views/reports/biDashboard';
const dataset = { id: 'sales', module: '销售管理', name: '销售', path: '/sales-management/orders', dimensions: ['store_id', 'currency', 'date', 'platform', 'region', 'status'].map(key => ({ key, label: key })), metrics: [{ key: 'gross_sales', kind: 'money' }, { key: 'order_count', kind: 'count' }], filters: ['store_id', 'currency', 'date_from', 'date_to', 'platform'], defaults: { dimensions: ['store_id', 'currency'], metrics: ['gross_sales', 'order_count'] } };
const base = () => newWidget(dataset).config;

describe('BI field layout', () => {
  it('moves a dimension into columns without duplicating it and switches to a pivot', () => {
    const next = moveField(base(), dataset, { kind: 'dimension', key: 'store_id' }, 'columns');
    expect(next.field_layout).toMatchObject({ rows: ['currency'], columns: ['store_id'] });
    expect(next.dimensions).toEqual(['currency', 'store_id']);
    expect(next.chart).toBe('pivot');
    expect(base().dimensions).toEqual(['store_id', 'currency']);
  });
  it('supports reordering metrics and rejects a field dropped into the wrong zone', () => {
    expect(moveField(base(), dataset, { kind: 'metric', key: 'order_count' }, 'metrics', 0).metrics).toEqual(['order_count', 'gross_sales']);
    expect(moveField(base(), dataset, { kind: 'metric', key: 'gross_sales' }, 'rows')).toBeNull();
    expect(moveField(base(), dataset, { kind: 'dimension', key: 'injected_sql' }, 'rows')).toBeNull();
  });
  it('removes a filter and its active value together, retaining explicit empty filter zones', () => {
    const config = base(); config.filters.store_id = '1';
    const next = removeField(config, dataset, 'store_id', 'filters');
    expect(next.filters).toEqual({}); expect(next.field_layout.filters).not.toContain('store_id');
    expect(fieldLayout({ ...next, field_layout: { ...next.field_layout, filters: [] } }, dataset).filters).toEqual([]);
  });
  it('keeps currency for monetary metrics and at least one metric', () => {
    expect(removeField(base(), dataset, 'currency', 'rows')).toBeNull();
    const config = base(); config.metrics = ['gross_sales'];
    expect(removeField(config, dataset, 'gross_sales', 'metrics')).toBeNull();
  });
  it('uses unambiguous multi-column keys and never fills missing cells or combines currencies', () => {
    const rows = [{ currency: 'PHP', store_id: 'A · B', date: 'C', gross_sales: '3' }, { currency: 'PHP', store_id: 'A', date: 'B · C', gross_sales: null }, { currency: 'CNY', store_id: 'A', date: 'B · C', gross_sales: '9' }];
    const config = { dimensions: ['currency', 'store_id', 'date'], field_layout: { columns: ['store_id', 'date'] } };
    const matrix = matrixRows(rows, config, 'gross_sales');
    expect(matrix.columns).toHaveLength(2); expect(matrix.rows).toHaveLength(2);
    expect(matrix.rows[0].cells[matrix.columns[1].key].value).toBeNull();
    expect(matrix.rows[1].cells[matrix.columns[0].key]).toBeUndefined();
    expect(matrix.rows[0].cells[matrix.columns[0].key].source).toBe(rows[0]);
  });
  it('breaks a trend across missing values and currencies while preserving source rows', () => {
    const rows = [{ store_id: 1, currency: 'PHP', gross_sales: 3 }, { store_id: 2, currency: 'PHP', gross_sales: null }, { store_id: 3, currency: 'PHP', gross_sales: -2 }, { store_id: 4, currency: 'CNY', gross_sales: 5 }];
    const model = chartData(rows, base(), 'gross_sales');
    expect(model.points).toHaveLength(3); expect(model.series).toHaveLength(3); expect(model.points[0].row).toBe(rows[0]);
  });
});

describe('BI dashboard filter semantics', () => {
  it('propagates supported global filters and reports incompatible ones without inventing a stock/store join', () => {
    const stock = { ...dataset, id: 'inventory', module: '库存管理', filters: ['warehouse_id', 'site_code', 'date_to'], dimensions: [{ key: 'warehouse_id' }], defaults: { dimensions: ['warehouse_id'], metrics: ['order_count'] } };
    const widget = newWidget(stock);
    const effective = queryWithLink(widget, [stock], { store_id: '1', warehouse_id: '2', date_to: '2026-09-30' });
    expect(effective.config.filters).toEqual({ warehouse_id: '2', date_to: '2026-09-30' });
    expect(effective.ignored).toEqual(['store_id']);
  });
  it('links peers by real shared dimensions and keeps SKU/status/date linkage in the source dataset', () => {
    const source = newWidget(dataset, 'bar', 'source'); source.config.dimensions.push('status', 'date');
    const peer = newWidget(dataset, 'bar', 'peer'); peer.config.filters.store_ids = '1,2';
    const link = selectionLink(source, { store_id: 1, currency: 'PHP', status: 'completed', date: '2026-09-29' });
    const effective = queryWithLink(peer, [dataset], {}, link);
    expect(effective.config.filters).toMatchObject({ store_id: 1, currency: 'PHP', date_from: '2026-09-29', date_to: '2026-09-29' });
    expect(effective.config.filters.store_ids).toBeUndefined();
    expect(queryWithLink(source, [dataset], {}, link).config.filters).toEqual({});
  });
  it('generates each business template only from currently authorized datasets', () => {
    expect(dashboardTemplate('销售管理', [dataset]).widgets.map(widget => widget.config.dataset)).toEqual(['sales', 'sales']);
    expect(dashboardTemplate('库存管理', [dataset]).widgets).toEqual([]);
    expect(dashboardTemplate('财务中心', [dataset]).widgets).toEqual([]);
  });
  it('keeps cost currency independent from transaction currency and removes cleared component filters', () => {
    const cost = { ...dataset, id: 'inventory_value', module: '财务中心', filters: ['currency', 'warehouse_id'] };
    const widget = newWidget(cost, 'card', 'cost'); widget.config.filters.currency = null;
    const effective = queryWithLink(widget, [cost], {}, { source: 'sale', dataset: 'sales', filters: { currency: 'PHP' }, local: {} });
    expect(effective.config.filters).toEqual({});
  });
  it('drills using the actual queried config and withholds grouped valuation routes until SKU expansion', () => {
    const widget = newWidget(dataset);
    const queried = { config: { ...widget.config, filters: { date_from: '2026-09-01', date_to: '2026-09-30' } } };
    expect(drillLocation(widget, { store_id: 2 }, queried, dataset)).toEqual({ path: dataset.path, query: { date_from: '2026-09-01', date_to: '2026-09-30', store_id: 2 } });
    expect(drillLocation({ config: { dataset: 'inventory_value', dimensions: ['warehouse_id'] } }, { warehouse_id: 1 }, { config: { dataset: 'inventory_value', dimensions: ['warehouse_id'], filters: {} } }, dataset)).toBeNull();
  });
});
