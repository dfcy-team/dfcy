import { describe, expect, it, vi } from 'vitest';

import { createRequestSequence, createSuccessfulAsyncCache } from '../src/utils/asyncRequestControl';

describe('异步请求性能控制', () => {
  it('合并并发请求、仅缓存成功结果，失败后允许重试', async () => {
    const loader = vi.fn()
      .mockResolvedValueOnce({ success: false })
      .mockResolvedValueOnce({ success: true, value: 2 });
    const cache = createSuccessfulAsyncCache(loader, (result) => result.success);

    const first = await Promise.all([cache.get('tenant-a'), cache.get('tenant-a')]);
    const retried = await cache.get('tenant-a');
    const cached = await cache.get('tenant-a');

    expect(first).toEqual([{ success: false }, { success: false }]);
    expect(retried).toEqual({ success: true, value: 2 });
    expect(cached).toBe(retried);
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('新请求开始后会使旧请求凭证失效', () => {
    const sequence = createRequestSequence();
    const oldRequest = sequence.begin();
    const currentRequest = sequence.begin();

    expect(oldRequest.isCurrent()).toBe(false);
    expect(currentRequest.isCurrent()).toBe(true);
  });
});
