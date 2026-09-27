export function parseBundleImportSpecification(raw, category) {
  const text = String(raw || '').trim();
  if (!text) return {};
  const dimensions = category?.spec_dimensions || [];
  if (!Array.isArray(dimensions) || !dimensions.length) throw new Error('该末级分类未设置规格维度，不能填写组合规格');
  const result = {};
  for (const segment of text.split(/[;；]/)) {
    const entry = segment.trim();
    if (!entry) continue;
    const separator = entry.indexOf('=');
    let dimension;
    let value;
    if (separator < 0) {
      value = entry;
      const matches = dimensions.filter((item) =>
        Array.isArray(item.values) && item.values.some((option) => String(option).trim() === value));
      if (matches.length > 1) throw new Error(`组合规格 ${entry} 对应多个规格维度，请填写“维度编码=规格值”`);
      dimension = matches[0] || (dimensions.length === 1 ? dimensions[0] : null);
      if (!dimension) throw new Error(`组合规格 ${entry} 无法确定规格维度，请填写“维度编码=规格值”`);
    } else {
      const code = entry.slice(0, separator).trim();
      value = entry.slice(separator + 1).trim();
      dimension = dimensions.find((item) => String(item.code) === code);
      if (!dimension) throw new Error(`组合规格维度 ${code} 不属于当前末级分类`);
    }
    const code = String(dimension.code);
    if (!value || value === '0') throw new Error(`组合规格维度 ${code} 缺少有效规格值`);
    if (Object.hasOwn(result, code)) throw new Error(`组合规格维度 ${code} 重复填写`);
    result[code] = value;
  }
  if (!Object.keys(result).length) throw new Error('组合规格格式错误，请填写“维度编码=规格值”');
  return result;
}
