import { describe, expect, it } from 'vitest';
import fs from 'node:fs';

const source = fs.readFileSync('src/views/products/ProductDetailData.vue', 'utf8');
const start = source.indexOf('    request = Promise.allSettled([');
const end = source.indexOf('    cache.promise = request;', start);
const load = new Function('cache', 'fetchProductCategories', 'fetchProductCategoryBackgroundColors',
  'fetchProductColors', 'fetchProductAttributes', 'collectionRows', 'mergeCategoryBackgroundColors',
  'const requestVersion = cache.version; let request;' + source.slice(start, end) + '; return request;');

describe('商品明细分类目录辅助资料降级', () => {
  const ok = (data) => ({ success: true, data });
  async function run(background, colors = ok([]), categories = ok([{ id: 1 }])) {
    const cache = { version: 1, promise: null, value: null };
    const result = await load(cache, async () => categories, background, async () => colors,
      async () => ok([]), (data) => data, (rows) => rows);
    return { cache, result };
  }
  it('背景色403仍显示分类，且不缓存残缺资料', async () => {
    const { result, cache } = await run(async () => ({ success: false, code: 'PERMISSION_DENIED' }));
    expect(result.categories).toEqual([{ id: 1 }]);
    expect(cache.value).toBeNull();
    expect(cache.promise).toBeNull();
  });
  it('辅助请求网络异常或颜色无权限仍显示分类', async () => {
    const { result } = await run(async () => { throw new Error('network'); }, { success: false });
    expect(result.categories).toEqual([{ id: 1 }]);
    expect(result.colors).toEqual([]);
  });
  it('分类本身无权限时保留失败信息', async () => {
    await expect(run(async () => ok([]), ok([]), { success: false, message: '无分类读取权限' }))
      .rejects.toThrow('无分类读取权限');
  });
});
