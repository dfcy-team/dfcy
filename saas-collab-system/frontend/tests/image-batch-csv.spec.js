import { describe, expect, it } from 'vitest';
import { parseImageCsv } from '../src/utils/imageBatchCsv';

describe('商品图片 CSV 异步解析器', () => {
  it('支持 BOM、CRLF、逗号/换行包裹字段和双引号转义', async () => {
    expect(await parseImageCsv('\ufeffsku,url\r\n"a,b","one\r\ntwo"\r\n"a""b",url\r\n'))
      .toEqual([['sku', 'url'], ['a,b', 'one\r\ntwo'], ['a"b', 'url']]);
  });

  it('空输入也报告有限进度，不产生除零结果', async () => {
    const progress = [];
    expect(await parseImageCsv('', (value) => progress.push(value))).toEqual([]);
    expect(progress).toEqual([100]);
    expect(progress.every((value) => Number.isFinite(value) && value >= 0 && value <= 100)).toBe(true);
  });

  it('解析大文件时定时器可获得执行且不丢行', async () => {
    let ticks = 0;
    const progress = [];
    const timer = setInterval(() => { ticks += 1; }, 0);
    try {
      const rows = await parseImageCsv(
        'sku,url\n' + 'SKU,https://example.test/image.png\n'.repeat(10000),
        (value) => progress.push(value),
      );
      expect(rows).toHaveLength(10001);
      expect(ticks).toBeGreaterThan(0);
      expect(progress.at(-1)).toBe(100);
      expect(progress.every((value) => Number.isFinite(value))).toBe(true);
    } finally {
      clearInterval(timer);
    }
  });

  it('长引号字段跨越 yield 边界时仍可解析', async () => {
    const progress = [];
    const value = 'x'.repeat(40 * 1024);
    const rows = await parseImageCsv(`sku,url\nSKU,"${value}"\n`, (item) => progress.push(item));
    expect(rows).toEqual([['sku', 'url'], ['SKU', value]]);
    expect(progress.some((item) => item < 100)).toBe(true);
  });

  it('拒绝未闭合引号', async () => {
    await expect(parseImageCsv('sku,url\nA,"broken')).rejects.toThrow('引号未闭合');
  });
});
