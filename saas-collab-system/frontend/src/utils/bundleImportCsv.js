export async function decodeBundleImportFile(file) {
  const bytes = await file.arrayBuffer();
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder('gb18030', { fatal: true }).decode(bytes);
  }
}

export function parseBundleCsvRecords(text) {
  const source = String(text || '').replace(/^\uFEFF/, '');
  const records = [];
  let values = [];
  let cell = '';
  let quoted = false;
  let line = 1;
  let recordLine = 1;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];
    if (character === '"' && quoted && next === '"') { cell += '"'; index += 1; continue; }
    if (character === '"') { quoted = !quoted; continue; }
    if (character === ',' && !quoted) { values.push(cell.trim()); cell = ''; continue; }
    if (character === '\r' || character === '\n') {
      if (character === '\r' && next === '\n') index += 1;
      if (quoted) {
        cell += '\n';
      } else {
        values.push(cell.trim());
        if (values.some(Boolean)) records.push({ line: recordLine, values });
        values = [];
        cell = '';
        recordLine = line + 1;
      }
      line += 1;
      continue;
    }
    cell += character;
  }
  if (quoted) throw new Error(`CSV 第 ${recordLine} 行引号未闭合`);
  values.push(cell.trim());
  if (values.some(Boolean)) records.push({ line: recordLine, values });
  return records;
}

export function bundleCsvHeaderIndex(headers, name) {
  const normalize = (value) => String(value || '').replace(/^\uFEFF/, '').replace(/^\*/, '').replace(/[\s\u3000]/g, '');
  return headers.findIndex((header) => normalize(header) === normalize(name));
}
