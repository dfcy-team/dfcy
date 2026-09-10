import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getProductDictionaryCache,
  invalidateProductDictionaryCache,
  PRODUCT_DICTIONARY_CACHE_EVENT,
  PRODUCT_DICTIONARY_CACHE_STORAGE_KEY,
  productDictionaryCacheScope,
  subscribeProductDictionaryCacheInvalidation,
} from '../src/utils/productDictionaryCache';

describe('商品字典缓存失效', () => {
  beforeEach(() => {
    const cache = getProductDictionaryCache();
    cache.value = null;
    cache.promise = null;
    cache.version = 0;
    window.localStorage.removeItem(PRODUCT_DICTIONARY_CACHE_STORAGE_KEY);
  });

  it('同一 SPA 保存颜色后清空快照并通知已挂载页面', () => {
    const cache = getProductDictionaryCache();
    cache.value = { categories: [{ id: 16, row_background_color: '#FFF4E6' }] };
    cache.promise = Promise.resolve(cache.value);
    const onInvalidated = vi.fn();
    const stop = subscribeProductDictionaryCacheInvalidation(onInvalidated);

    invalidateProductDictionaryCache();

    expect(cache.value).toBeNull();
    expect(cache.promise).toBeNull();
    expect(onInvalidated).toHaveBeenCalledTimes(1);
    stop();
  });

  it('另一 tab 的 storage 更新会清空快照并触发重新加载', () => {
    const cache = getProductDictionaryCache();
    cache.value = { categories: [{ id: 16, row_background_color: '#FFF4E6' }] };
    const onInvalidated = vi.fn();
    const stop = subscribeProductDictionaryCacheInvalidation(onInvalidated);
    const event = new StorageEvent('storage', {
      key: PRODUCT_DICTIONARY_CACHE_STORAGE_KEY,
      newValue: `test-${Date.now()}`,
    });

    window.dispatchEvent(event);

    expect(cache.value).toBeNull();
    expect(onInvalidated).toHaveBeenCalledTimes(1);
    expect(PRODUCT_DICTIONARY_CACHE_EVENT).toBe('saas-collab:product-dictionary-invalidated');
    stop();
  });

  it('按租户和用户 scope 隔离缓存，避免身份切换复用旧字典', () => {
    expect(productDictionaryCacheScope({ tenant_id: 7, user_id: 11 }))
      .not.toBe(productDictionaryCacheScope({ tenant_id: 8, user_id: 11 }));
    expect(productDictionaryCacheScope({ tenant_id: 7, user_id: 11 }))
      .not.toBe(productDictionaryCacheScope({ tenant_id: 7, user_id: 12 }));
    expect(getProductDictionaryCache('tenant-7:user-11'))
      .not.toBe(getProductDictionaryCache('tenant-8:user-11'));
  });
});
