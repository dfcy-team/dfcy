const textEncoder = new TextEncoder();

export const BIGSELLER_PRODUCT_HEADERS = [
  '*SKU编号(必填)', '*名称(必填)', '分类', 'GTIN', '仓库', '库存', '成本价', '参考成本价', '促销价',
  '商品备用名', '品牌', '材质', '用途', '标签', '参考售价', '商品起售日期', '净重(g)', '毛重(g)', '长(cm)',
  '宽(cm)', '高(cm)', '体积(cm3)', 'Image URL', '效期管理', '保质期天数', '临期预警天数', '商品备注', '基本单位',
  '辅助单位1', '换算规则1', '条形码1', '辅助单位2', '换算规则2', '条形码2', '辅助单位3', '换算规则3',
  '条形码3', '辅助单位4', '换算规则4', '条形码4', '辅助单位5', '换算规则5', '条形码5', '采购单位',
  '是否分销', '基本售价', '分销最低售价', '序列号管理',
];

export const BIGSELLER_BUNDLE_HEADERS = [
  '*SKU编号', '*名称', '仓库', '分类', '商品备用名', '品牌', '材质', '用途', '标签', '参考成本价', '参考售价',
  '促销价', 'Image URL', '商品备注',
  ...Array.from({ length: 20 }, (_, index) => {
    const number = index + 1;
    const required = number === 1 ? '*' : '';
    return [`${required}单品SKU${number}`, `${required}SKU${number}数量`, `SKU${number}成本价分摊比`];
  }).flat(),
];

function xmlEscape(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function columnName(index) {
  let value = index + 1;
  let output = '';
  while (value) {
    value -= 1;
    output = String.fromCharCode(65 + (value % 26)) + output;
    value = Math.floor(value / 26);
  }
  return output;
}

function cellXml(value, reference, style = 0) {
  if (typeof value === 'number' && Number.isFinite(value)) return `<c r="${reference}" s="${style}"><v>${value}</v></c>`;
  return `<c r="${reference}" s="${style}" t="inlineStr"><is><t xml:space="preserve">${xmlEscape(value)}</t></is></c>`;
}

function worksheetXml(headers, rows) {
  const allRows = [headers, ...rows];
  const sheetRows = allRows.map((row, rowIndex) => {
    const cells = headers.map((_, columnIndex) => cellXml(
      row?.[columnIndex] ?? '',
      `${columnName(columnIndex)}${rowIndex + 1}`,
      rowIndex === 0 ? 1 : 0,
    )).join('');
    return `<row r="${rowIndex + 1}">${cells}</row>`;
  }).join('');
  const lastCell = `${columnName(Math.max(0, headers.length - 1))}${Math.max(1, allRows.length)}`;
  const columns = headers.map((header, index) => {
    const width = Math.min(38, Math.max(12, String(header).length * 1.8));
    return `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`;
  }).join('');
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:${lastCell}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${columns}</cols><sheetData>${sheetRows}</sheetData><autoFilter ref="A1:${columnName(headers.length - 1)}1"/></worksheet>`;
}

let crcTable;
function crc32(bytes) {
  if (!crcTable) {
    crcTable = Array.from({ length: 256 }, (_, index) => {
      let value = index;
      for (let bit = 0; bit < 8; bit += 1) value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
      return value >>> 0;
    });
  }
  let crc = 0xffffffff;
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function uint16(value) {
  return new Uint8Array([value & 0xff, (value >>> 8) & 0xff]);
}

function uint32(value) {
  return new Uint8Array([value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff]);
}

function concatBytes(parts) {
  const output = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) { output.set(part, offset); offset += part.length; }
  return output;
}

function zipStore(files) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  for (const [name, content] of files) {
    const nameBytes = textEncoder.encode(name);
    const data = textEncoder.encode(content);
    const checksum = crc32(data);
    const local = concatBytes([
      uint32(0x04034b50), uint16(20), uint16(0x0800), uint16(0), uint16(0), uint16(0),
      uint32(checksum), uint32(data.length), uint32(data.length), uint16(nameBytes.length), uint16(0), nameBytes, data,
    ]);
    localParts.push(local);
    centralParts.push(concatBytes([
      uint32(0x02014b50), uint16(20), uint16(20), uint16(0x0800), uint16(0), uint16(0), uint16(0),
      uint32(checksum), uint32(data.length), uint32(data.length), uint16(nameBytes.length), uint16(0), uint16(0),
      uint16(0), uint16(0), uint32(0), uint32(offset), nameBytes,
    ]));
    offset += local.length;
  }
  const central = concatBytes(centralParts);
  const end = concatBytes([
    uint32(0x06054b50), uint16(0), uint16(0), uint16(files.length), uint16(files.length),
    uint32(central.length), uint32(offset), uint16(0),
  ]);
  return concatBytes([...localParts, central, end]);
}

export function buildBigSellerWorkbook(headers, rows, sheetName = 'SKU') {
  if (!Array.isArray(headers) || !headers.length) throw new Error('导出表头不能为空');
  const safeName = String(sheetName || 'SKU').replace(/[\\/*?:[\]]/g, '').slice(0, 31) || 'SKU';
  const files = [
    ['[Content_Types].xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`],
    ['_rels/.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
    ['xl/workbook.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${xmlEscape(safeName)}" sheetId="1" r:id="rId1"/></sheets></workbook>`],
    ['xl/_rels/workbook.xml.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`],
    ['xl/styles.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs></styleSheet>`],
    ['xl/worksheets/sheet1.xml', worksheetXml(headers, rows)],
  ];
  return zipStore(files);
}

function numericOrBlank(value) {
  if (value === null || value === undefined || value === '') return '';
  const number = Number(value);
  return Number.isFinite(number) ? number : '';
}

export function mapProductDetailsToBigSellerRows(details = []) {
  return details.filter((row) => row?.sku_code).map((row) => {
    const output = Array(BIGSELLER_PRODUCT_HEADERS.length).fill('');
    output[0] = String(row.sku_code);
    output[1] = row.sku_product_name || row.product_name || row.spu_product_name || row.sku_code;
    output[2] = row.category_name || '';
    output[6] = numericOrBlank(row.purchase_price);
    output[7] = numericOrBlank(row.purchase_price);
    output[16] = numericOrBlank(row.net_weight);
    output[17] = numericOrBlank(row.package_weight);
    output[18] = numericOrBlank(row.package_length_cm);
    output[19] = numericOrBlank(row.package_width_cm);
    output[20] = numericOrBlank(row.package_height_cm);
    const cubicMetres = numericOrBlank(row.package_volume);
    output[21] = cubicMetres === '' ? '' : cubicMetres * 1000000;
    output[22] = row.image_url || row.image || '';
    output[26] = row.description || '';
    output[27] = row.unit || '个';
    output[43] = row.purchase_unit || row.unit || '个';
    return output;
  });
}

export function mapBundlesToBigSellerRows(bundleSpus = [], skus = [], components = []) {
  const bundleIds = new Set(bundleSpus.map((item) => String(item.id)));
  return skus.filter((sku) => bundleIds.has(String(sku.spu))).map((sku) => {
    const spu = bundleSpus.find((item) => String(item.id) === String(sku.spu)) || {};
    const relations = components.filter((item) => String(item.bundle_sku) === String(sku.id)).slice(0, 20);
    const output = Array(BIGSELLER_BUNDLE_HEADERS.length).fill('');
    output[0] = String(sku.sku_code || '');
    output[1] = sku.sku_product_name || spu.product_name || sku.sku_code || '';
    output[3] = spu.category_name || '';
    output[9] = numericOrBlank(sku.purchase_price);
    output[12] = sku.image_url || spu.image_url || '';
    relations.forEach((relation, index) => {
      const start = 14 + index * 3;
      output[start] = relation.component_sku_code || '';
      output[start + 1] = numericOrBlank(relation.quantity) || 1;
      const allocationRatio = numericOrBlank(relation.cost_allocation_ratio);
      output[start + 2] = allocationRatio === '' ? 1 : allocationRatio;
    });
    return output;
  }).filter((row) => row[0] && row[14]);
}

function downloadWorkbook(filename, headers, rows, sheetName) {
  const bytes = buildBigSellerWorkbook(headers, rows, sheetName);
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function downloadBigSellerProductWorkbook(details, filename = `BigSeller商品SKU_${Date.now()}.xlsx`) {
  const rows = mapProductDetailsToBigSellerRows(details);
  if (!rows.length) throw new Error('没有可导出的已生成 SKU');
  downloadWorkbook(filename, BIGSELLER_PRODUCT_HEADERS, rows, 'SKU');
  return rows.length;
}

export function downloadBigSellerBundleWorkbook(bundleSpus, skus, components, filename = `BigSeller组合商品SKU_${Date.now()}.xlsx`) {
  const rows = mapBundlesToBigSellerRows(bundleSpus, skus, components);
  if (!rows.length) throw new Error('选中的组合商品没有完整的组合 SKU 关系');
  downloadWorkbook(filename, BIGSELLER_BUNDLE_HEADERS, rows, 'Sheet1');
  return rows.length;
}
