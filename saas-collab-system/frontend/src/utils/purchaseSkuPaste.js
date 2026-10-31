export function parsePurchaseSkuPaste(text, mode) {
  const expected = { sku: 1, quantity: 2, price: 3 }[mode];
  if (!expected) return { rows: [], errors: ['粘贴格式无效。'] };
  const rows = String(text || '').replace(/\r/g, '').split('\n')
    .map((line, index) => ({ row: index + 1, cells: line.split('\t').map(value => value.trim()) }))
    .filter(row => row.cells.some(Boolean)).map((row, index) => ({ ...row, requestRow: index + 1 }));
  if (rows.length > 500) return { rows: [], errors: ['最多粘贴 500 行。'] };
  const errors = [];
  for (const row of rows) {
    const [code, quantityRaw, priceRaw] = row.cells;
    if (row.cells.length !== expected || !code) errors.push(`第 ${row.row} 行：列数或 SKU 无效。`);
    row.code = code;
    row.quantity = mode === 'sku' ? 1 : Number(quantityRaw);
    row.price = null;
    if (!Number.isSafeInteger(row.quantity) || row.quantity < 1 || row.quantity > 2147483647) errors.push(`第 ${row.row} 行：数量须为 1–2147483647 的正整数。`);
    if (mode === 'price') {
      if (!/^(?:\d{1,10})(?:\.\d{1,4})?$/.test(priceRaw || '')) errors.push(`第 ${row.row} 行：单价须为不超过 10 位整数、最多 4 位小数的非负数。`);
      else row.price = Number(priceRaw);
    }
  }
  return { rows, errors };
}

export function buildPurchaseSkuPasteLines(rows, resolved, existingIds, sourceKind) {
  const errors = [], byRow = new Map(resolved.map(item => [item.row, item]));
  const existing = new Set(existingIds), seen = new Map();
  for (const row of rows) {
    const result = byRow.get(row.requestRow);
    if (!result || result.error || !result.item) errors.push(`第 ${row.row} 行：${result?.error || 'SKU 解析失败'}（${row.code}）。`);
    else if (existing.has(result.item.id)) errors.push(`第 ${row.row} 行：SKU 已存在采购单中（${row.code}）。`);
    else seen.set(result.item.id, [...(seen.get(result.item.id) || []), row.row]);
  }
  [...seen.values()].filter(indices => indices.length > 1).flat().forEach(row => errors.push(`第 ${row} 行：与粘贴的其他编码指向同一 SKU。`));
  if (errors.length) return { lines: [], errors };
  return { errors, lines: rows.map(row => {
    const item = byRow.get(row.requestRow).item;
    return { sku_id: item.id, sku: item.sku, legacy_sku_code: item.legacy_sku_code || '', name: item.name,
      product_details: item.product_details || {}, quantity: row.quantity,
      product_reference_price: item.product_reference_price, supplier_reference_price: item.supplier_reference_price,
      unit_price: row.price ?? (item.supplier_reference_price ?? item.product_reference_price), price_defaulted: row.price === null,
      ...(sourceKind === 'import' ? { import_row_number: null } : {}) };
  }) };
}
