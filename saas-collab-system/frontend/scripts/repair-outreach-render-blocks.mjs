import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

// Hand-written VNodes must not join a compiled parent's dynamicChildren array.
// Keep each panel a stable block, but fully diff its variable child structure.
export function repairOutreachRenderBlocks(source) {
  let result = source;
  for (const [name, next] of [
    ['renderPriority', 'function renderActivity(){'],
    ['renderActivity', 'let outreachLoadSeq'],
  ]) {
    const start = result.indexOf(`function ${name}(){`);
    const end = result.indexOf(next, start);
    if (start < 0 || end < 0) throw new Error(`Missing renderer boundary: ${name}`);
    let panel = result.slice(start, end);
    if ((panel.match(/return n\("section"/g) || []).length !== 1) {
      throw new Error(`Unexpected renderer root: ${name}`);
    }
    panel = panel.replace('return n("section"', 'r(true); const tree=C("section"');
    const close = panel.lastIndexOf(']);');
    if (close < 0) throw new Error(`Missing renderer end: ${name}`);
    panel = panel.slice(0, close) + panel.slice(close).replace(
      ']);', ']); tree.dynamicChildren=null; tree.patchFlag=-2; return tree;',
    );
    result = result.slice(0, start) + panel + result.slice(end);
  }
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [input, output] = process.argv.slice(2);
  if (!input || !output || input === output) throw new Error('Provide separate input and output paths');
  const repaired = repairOutreachRenderBlocks(readFileSync(input, 'utf8'));
  writeFileSync(output, repaired, { flag: 'wx' });
}
