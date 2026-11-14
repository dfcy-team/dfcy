import { describe, expect, it } from 'vitest';
import { parsePurchaseSkuPaste } from './purchaseSkuPaste';
import { planShipmentSkuPaste, shipmentGoodsValue } from './shipmentSkuPaste';

const source = { id: 10, purchase_order_id: 3, sku_id: 21, sku: 'NEW-21', legacy_sku_code: 'OLD-21', unit_price: '2.50' };
const other = { id: 11, purchase_order_id: 3, sku_id: 22, sku: 'NEW-22', unit_price: '7.50' };
const parse = (text, mode = 'quantity') => parsePurchaseSkuPaste(text, mode).rows;

describe('shipment draft SKU paste', () => {
  it('plans quantity and price updates by old SKU while preserving the source', () => {
    const line = { ...source, id: 90, purchase_line_id: 10, quantity: 8, unit_price: 4 };
    const plan = planShipmentSkuPaste(parse('old-21\t3\t12.8408\nNEW-22\t2\t6', 'price'), [line], [source, other]);
    expect(plan.errors).toEqual([]);
    expect(plan.updates).toEqual([{ line, quantity: 3, price: 12.8408 }]);
    expect(plan.additions).toMatchObject([{ sku_id: 22, purchase_line_id: 11, purchase_order_id: 3, quantity: 2, unit_price: 6 }]);
    expect(line).toMatchObject({ id: 90, quantity: 8, purchase_line_id: 10, unit_price: 4 });
  });

  it('keeps existing quantities in SKU-only mode and uses source price for additions', () => {
    const plan = planShipmentSkuPaste(parse('OLD-21\nNEW-22', 'sku'), [source], [source, other]);
    expect(plan.errors).toEqual([]);
    expect(plan.updates).toEqual([]);
    expect(plan.additions).toMatchObject([{ quantity: 1, unit_price: 7.5 }]);
  });

  it('flags ambiguous sources, duplicate aliases and unknown items', () => {
    const plan = planShipmentSkuPaste(parse('NEW-21\t1\nOLD-21\t2\nOUTSIDE\t3'), [], [source, { ...source, id: 12 }]);
    expect(plan.errors).toHaveLength(3);
    expect(plan.additions).toEqual([]);
    expect(planShipmentSkuPaste(parse('NEW-21\t1'), [source, source], [source]).errors).toHaveLength(1);
  });

  it('counts missing prices and sums four-place prices across the draft', () => {
    expect(shipmentGoodsValue([
      { sku_id: 1, quantity: 3, unit_price: '1000.0001' },
      { sku_id: 2, quantity: 1, unit_price: 0 },
      { sku_id: 3, quantity: 1, unit_price: null },
      { sku_id: null, quantity: 1, unit_price: null },
    ])).toEqual({ amount: '3,000.0003', unpriced: 1 });
  });
});
