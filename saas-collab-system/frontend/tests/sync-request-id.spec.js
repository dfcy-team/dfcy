import { webcrypto } from 'node:crypto';
import { afterEach, expect, it, vi } from 'vitest';
import { syncRequestId } from '../src/utils/syncRequestId';

afterEach(() => vi.unstubAllGlobals());

it('uses native UUID when available', () => {
  vi.stubGlobal('crypto', { randomUUID: () => 'native-uuid' });
  expect(syncRequestId()).toBe('native-uuid');
});

it('creates distinct UUID v4 values without randomUUID on LAN HTTP', () => {
  vi.stubGlobal('crypto', { getRandomValues: bytes => webcrypto.getRandomValues(bytes) });
  const values = Array.from({ length: 100 }, syncRequestId);
  expect(new Set(values).size).toBe(100);
  for (const value of values) expect(value).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

it('fails clearly instead of generating weak identifiers without crypto', () => {
  vi.stubGlobal('crypto', undefined);
  expect(syncRequestId).toThrow('当前浏览器不支持安全请求编号');
});
