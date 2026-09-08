export const PRODUCT_DICTIONARY_CACHE_EVENT = 'saas-collab:product-dictionary-invalidated';
export const PRODUCT_DICTIONARY_CACHE_STORAGE_KEY = 'saas-collab:product-category-background-colors-updated-at';

const cachesByScope = new Map();
let invalidationGeneration = 0;

let observedStorageVersion = readStorageVersion();

function readStorageVersion() {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(PRODUCT_DICTIONARY_CACHE_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

function createCache() {
  return {
    value: null,
    promise: null,
    version: 0,
  };
}

function resetCache(cache) {
  cache.value = null;
  cache.promise = null;
  cache.version += 1;
}

function resetAllCaches() {
  cachesByScope.forEach((cache) => resetCache(cache));
}

export function getProductDictionaryCache(scope = 'default') {
  const key = String(scope || 'default');
  if (!cachesByScope.has(key)) cachesByScope.set(key, createCache());
  return cachesByScope.get(key);
}

/** Keep tenant and user data dictionaries from sharing one in-memory entry. */
export function productDictionaryCacheScope(user) {
  const tenant = user?.tenant_id ?? user?.tenant?.id ?? 'anonymous-tenant';
  const actor = user?.user_id ?? user?.id ?? user?.username ?? 'anonymous-user';
  return `${tenant}:${actor}`;
}

/**
 * Drop the shared dictionary snapshot after a settings mutation.  The
 * browser event keeps already-mounted pages in this tab in sync, while the
 * storage marker lets another tab notice the update when it regains focus.
 */
export function invalidateProductDictionaryCache() {
  invalidationGeneration += 1;
  resetAllCaches();
  if (typeof window === 'undefined') return;

  const nextTimestamp = Math.max(Date.now(), Number(observedStorageVersion) + 1 || 0);
  observedStorageVersion = String(nextTimestamp);
  window.dispatchEvent(new CustomEvent(PRODUCT_DICTIONARY_CACHE_EVENT, {
    detail: { generation: invalidationGeneration },
  }));
  try {
    window.localStorage.setItem(PRODUCT_DICTIONARY_CACHE_STORAGE_KEY, observedStorageVersion);
  } catch {
    // Private browsing or disabled storage should not prevent the same-tab
    // CustomEvent from invalidating the in-memory cache.
  }
}

/**
 * Subscribe to cache invalidation from settings updates in this or another
 * browser tab.  The visibility check covers tabs that were backgrounded
 * while the storage event was delivered or throttled.
 */
export function subscribeProductDictionaryCacheInvalidation(handler) {
  if (typeof window === 'undefined') return () => {};

  const onCustomEvent = (event) => {
    if (event?.detail?.generation !== invalidationGeneration) {
      invalidationGeneration += 1;
      resetAllCaches();
    }
    handler?.();
  };
  const onStorage = (event) => {
    if (event.key !== PRODUCT_DICTIONARY_CACHE_STORAGE_KEY || !event.newValue || event.newValue === observedStorageVersion) return;
    observedStorageVersion = event.newValue;
    invalidationGeneration += 1;
    resetAllCaches();
    handler?.();
  };
  const onVisibilityChange = () => {
    if (document.visibilityState !== 'visible') return;
    const nextVersion = readStorageVersion();
    if (!nextVersion || nextVersion === observedStorageVersion) return;
    observedStorageVersion = nextVersion;
    invalidationGeneration += 1;
    resetAllCaches();
    handler?.();
  };

  window.addEventListener(PRODUCT_DICTIONARY_CACHE_EVENT, onCustomEvent);
  window.addEventListener('storage', onStorage);
  document.addEventListener('visibilitychange', onVisibilityChange);
  return () => {
    window.removeEventListener(PRODUCT_DICTIONARY_CACHE_EVENT, onCustomEvent);
    window.removeEventListener('storage', onStorage);
    document.removeEventListener('visibilitychange', onVisibilityChange);
  };
}
