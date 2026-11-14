import { amountUnits } from './payeeSettlement';

export function planShipmentSkuPaste(rows, existingLines, sourceLines) {
  const byCode = new Map();
  for (const line of [...existingLines, ...sourceLines]) {
    if (!line.sku_id) continue;
    for (const code of [line.sku || line.sku_code, line.legacy_sku_code]) {
      if (!code) continue;
      const key = code.trim().toLowerCase();
      if (!byCode.has(key)) byCode.set(key, new Set());
      byCode.get(key).add(String(line.sku_id));
    }
  }

  const updates = [], additions = [], errors = [], seen = new Set();
  for (const row of rows) {
    const ids = byCode.get(row.code.toLowerCase());
    if (!ids?.size) {
      errors.push(`第 ${row.row} 行：${row.code} 不在草稿或已选采购来源中，请添加来源采购单，或手动添加采购单外 SKU。`);
      continue;
    }
    const [id] = ids;
    if (ids.size > 1 || seen.has(id)) {
      errors.push(`第 ${row.row} 行：${row.code} 匹配多个 SKU 或与其他粘贴行重复，请核对编码。`);
      continue;
    }
    seen.add(id);
    const existing = existingLines.filter(line => String(line.sku_id) === id);
    const sources = sourceLines.filter(line => String(line.sku_id) === id);
    if (existing.length > 1 || (!existing.length && sources.length !== 1)
        || (existing.length && !existing[0].purchase_line_id && sources.length > 1)) {
      errors.push(`第 ${row.row} 行：${row.code} 有多条发货行或采购来源，请在商品明细中选择来源并调整数量。`);
      continue;
    }
    if (existing.length) {
      if (row.hasQuantity) updates.push({ line: existing[0], quantity: row.quantity, price: row.price });
      continue;
    }

    const [source] = sources;
    additions.push({
      sku_id: source.sku_id, sku: source.sku || source.sku_code,
      legacy_sku_code: source.legacy_sku_code || '',
      product_name: source.product_name || source.name,
      image_preview_url: source.image_preview_url || source.product_details?.image_url || '',
      purchase_line_id: source.id, purchase_order_id: source.purchase_order_id,
      quantity: row.quantity, unit_price: row.price ?? (source.unit_price == null ? null : Number(source.unit_price)),
    });
  }
  if (existingLines.length + additions.length > 500) errors.push('发货单最多 500 行商品。');
  return { updates, additions, errors };
}

export function shipmentGoodsValue(lines) {
  let units = 0n;
  let unpriced = 0;
  for (const line of lines) {
    const quantity = Number(line.quantity);
    if (!line.sku_id || !Number.isSafeInteger(quantity) || quantity < 1) continue;
    try {
      units += amountUnits(line.unit_price) * BigInt(quantity);
    } catch {
      unpriced += 1;
    }
  }
  const whole = (units / 10000n).toLocaleString('zh-CN');
  const fraction = String(units % 10000n).padStart(4, '0').replace(/0{0,2}$/, '');
  return { amount: `${whole}.${fraction}`, unpriced };
}
