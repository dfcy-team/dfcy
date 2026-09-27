const csvCell = (value) => {
  const raw = String(value ?? '');
  const safe = /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
  return `"${safe.replaceAll('"', '""')}"`;
};

export function buildCostImportErrorCsv(preview = {}) {
  const sourceRows = new Map((preview.error_rows || []).map((item) => [item.row, item.values || []]));
  const headers = ['异常批次', '行号', '字段', '错误原因', ...(preview.source_headers || [])];
  const rows = [headers, ...(preview.errors || []).map((item) => [
    preview.error_batch_id || '', item.row || '', item.field || item.code || '', item.message || '',
    ...(sourceRows.get(item.row) || []),
  ])];
  return `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}\r\n`;
}
