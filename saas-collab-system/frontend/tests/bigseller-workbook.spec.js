import { describe, expect, it } from 'vitest';
import {
  BIGSELLER_BUNDLE_HEADERS,
  BIGSELLER_PRODUCT_HEADERS,
  buildBigSellerWorkbook,
  mapBundlesToBigSellerRows,
  mapProductDetailsToBigSellerRows,
} from '../src/utils/bigsellerWorkbook';

function storedZipEntries(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const decoder = new TextDecoder();
  const entries = new Map();
  let offset = 0;
  while (offset + 30 <= bytes.length && view.getUint32(offset, true) === 0x04034b50) {
    const size = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const extraLength = view.getUint16(offset + 28, true);
    const nameStart = offset + 30;
    const dataStart = nameStart + nameLength + extraLength;
    const name = decoder.decode(bytes.slice(nameStart, nameStart + nameLength));
    entries.set(name, decoder.decode(bytes.slice(dataStart, dataStart + size)));
    offset = dataStart + size;
  }
  return entries;
}

describe('BigSeller xlsx 生成', () => {
  it('按用户提供模板保留普通表和组合表的完整列顺序', () => {
    expect(BIGSELLER_PRODUCT_HEADERS).toHaveLength(48);
    expect(BIGSELLER_PRODUCT_HEADERS.slice(0, 2)).toEqual(['*SKU编号(必填)', '*名称(必填)']);
    expect(BIGSELLER_BUNDLE_HEADERS).toHaveLength(74);
    expect(BIGSELLER_BUNDLE_HEADERS.slice(14, 20)).toEqual(['*单品SKU1', '*SKU1数量', 'SKU1成本价分摊比', '单品SKU2', 'SKU2数量', 'SKU2成本价分摊比']);
    expect(BIGSELLER_BUNDLE_HEADERS.at(-1)).toBe('SKU20成本价分摊比');
  });

  it('映射商品明细的 SKU、名称、成本、物理尺寸和图片', () => {
    const rows = mapProductDetailsToBigSellerRows([{
      sku_code: '001-A', sku_product_name: '测试商品', purchase_price: '12.5', package_weight: '300',
      package_volume: '0.002', package_length_cm: 10, package_width_cm: 20, package_height_cm: 30, image_url: 'https://example.com/a.jpg', unit: '件',
    }, { legacy_sku_code: 'OLD' }]);
    expect(rows).toHaveLength(1);
    expect(rows[0][0]).toBe('001-A');
    expect(rows[0][1]).toBe('测试商品');
    expect(rows[0][6]).toBe(12.5);
    expect(rows[0][21]).toBe(2000);
    expect(rows[0][22]).toBe('https://example.com/a.jpg');
    expect(rows[0][27]).toBe('件');
  });

  it('将组成关系展开到 BigSeller 的单品 SKU 三列组', () => {
    const rows = mapBundlesToBigSellerRows(
      [{ id: 8, product_name: '组合商品' }],
      [{ id: 9, spu: 8, sku_code: 'BUNDLE-01' }],
      [{ bundle_sku: 9, component_sku_code: 'SINGLE-01', quantity: 2, cost_allocation_ratio: 0.6 }],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].slice(0, 2)).toEqual(['BUNDLE-01', '组合商品']);
    expect(rows[0].slice(14, 17)).toEqual(['SINGLE-01', 2, 0.6]);

    const zeroRatio = mapBundlesToBigSellerRows(
      [{ id: 8, product_name: '组合商品' }],
      [{ id: 9, spu: 8, sku_code: 'BUNDLE-01' }],
      [{ bundle_sku: 9, component_sku_code: 'SINGLE-01', quantity: 1, cost_allocation_ratio: 0 }],
    );
    expect(zeroRatio[0][16]).toBe(0);
  });

  it('生成可解包的 Office Open XML 文件，并写入中文列头和数据', () => {
    const bytes = buildBigSellerWorkbook(['*SKU编号', '*名称'], [['001-A', '测试商品']], 'SKU');
    expect([...bytes.slice(0, 4)]).toEqual([0x50, 0x4b, 0x03, 0x04]);
    const entries = storedZipEntries(bytes);
    expect(entries.has('[Content_Types].xml')).toBe(true);
    expect(entries.get('xl/workbook.xml')).toContain('sheet name="SKU"');
    expect(entries.get('xl/worksheets/sheet1.xml')).toContain('*SKU编号');
    expect(entries.get('xl/worksheets/sheet1.xml')).toContain('测试商品');
  });
});
