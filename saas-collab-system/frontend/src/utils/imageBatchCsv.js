const CSV_YIELD_BYTES = 32 * 1024;

/**
 * Give the browser a chance to paint and process input events.
 * A timer (rather than a resolved promise) yields to the macrotask queue,
 * which is important for very large CSV files.
 */
export const yieldToPage = () => new Promise((resolve) => setTimeout(resolve, 0));

/**
 * Parse the small, RFC-4180-compatible subset used by the image import flow.
 * Quoted values may contain commas and line breaks; a pair of quotes inside a
 * quoted value represents one literal quote. Blank rows are ignored.
 *
 * @param {unknown} text CSV text
 * @param {(percent: number) => void} onProgress progress callback, 0..100
 * @returns {Promise<string[][]>}
 */
export async function parseImageCsv(text, onProgress = () => {}) {
  const source = String(text ?? '').replace(/^\uFEFF/, '');
  const output = [];
  let row = [];
  let cell = '';
  let quoted = false;
  let nextYield = CSV_YIELD_BYTES;

  for (let index = 0; index < source.length; index += 1) {
    // Check the source index instead of the row count so a single very long
    // quoted URL still yields to the page.
    if (index >= nextYield) {
      const percent = source.length ? Math.min(99, Math.floor((index / source.length) * 100)) : 0;
      onProgress(percent);
      await yieldToPage();
      nextYield = index + CSV_YIELD_BYTES;
    }

    const character = source[index];
    const next = source[index + 1];
    if (character === '"' && quoted && next === '"') {
      cell += '"';
      index += 1;
      continue;
    }
    if (character === '"') {
      quoted = !quoted;
      continue;
    }
    if (character === ',' && !quoted) {
      row.push(cell.trim());
      cell = '';
      continue;
    }
    if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && next === '\n') index += 1;
      row.push(cell.trim());
      if (row.some((value) => value !== '')) output.push(row);
      row = [];
      cell = '';
      continue;
    }
    cell += character;
  }

  if (quoted) throw new Error('CSV 引号未闭合，请检查文件格式。');
  row.push(cell.trim());
  if (row.some((value) => value !== '')) output.push(row);
  onProgress(100);
  return output;
}
