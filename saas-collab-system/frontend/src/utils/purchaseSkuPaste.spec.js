import { describe, expect, it } from 'vitest';
import { buildPurchaseSkuPasteLines, parsePurchaseSkuPaste } from './purchaseSkuPaste';

describe('purchase SKU paste', () => {
  it('parses all three TSV formats and validates quantities and prices', () => {
    expect(parsePurchaseSkuPaste('A\nB', 'sku').rows.map(row => row.quantity)).toEqual([1, 1]);
    expect(parsePurchaseSkuPaste('A\t2', 'quantity').errors).toEqual([]);
    expect(parsePurchaseSkuPaste('A\t1.5', 'quantity').errors[0]).toContain('第 1 行');
    expect(parsePurchaseSkuPaste('A\t999999999999999999999', 'quantity').errors[0]).toContain('2147483647');
    expect(parsePurchaseSkuPaste('A\t2\t0.12345', 'price').errors[0]).toContain('单价');
    expect(parsePurchaseSkuPaste('A\t2\t99999999999', 'price').errors[0]).toContain('单价');
    expect(parsePurchaseSkuPaste('A\t2\t0', 'price').rows[0].price).toBe(0);
    expect(parsePurchaseSkuPaste(Array(501).fill('A').join('\n'), 'sku').errors[0]).toContain('500');
  });

  it('uses SKU ids for pasted and existing row conflict detection', () => {
    const parsed = parsePurchaseSkuPaste('NEW\nOLD', 'sku').rows;
    const resolved = [{ row: 1, item: { id: 7, sku: 'NEW', supplier_reference_price: '3.5' } },
      { row: 2, item: { id: 7, sku: 'NEW', legacy_sku_code: 'OLD' } }];
    expect(buildPurchaseSkuPasteLines(parsed, resolved, [], null).errors).toHaveLength(2);
    const conflict = buildPurchaseSkuPasteLines([parsed[0]], [resolved[0]], [7], null);
    expect(conflict.errors[0]).toContain('已存在采购单');
  });

  it('keeps typed price and supplier fallback, and marks imported additions unattributed', () => {
    const typed = parsePurchaseSkuPaste('SKU-1\t4\t0', 'price').rows;
    const result = buildPurchaseSkuPasteLines(typed, [{ row: 1, item: { id: 8, sku: 'SKU-1', supplier_reference_price: '5.25' } }], [], 'import');
    expect(result.lines[0]).toMatchObject({ quantity: 4, unit_price: 0, price_defaulted: false, import_row_number: null });
    const defaulted = buildPurchaseSkuPasteLines(parsePurchaseSkuPaste('SKU-2', 'sku').rows,
      [{ row: 1, item: { id: 9, sku: 'SKU-2', supplier_reference_price: '6.5' } }], [], null);
    expect(defaulted.lines[0]).toMatchObject({ quantity: 1, unit_price: '6.5', price_defaulted: true });
  });
});
