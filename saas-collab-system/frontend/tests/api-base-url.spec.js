import { describe, expect, it } from 'vitest';
import { normalizeApiBaseUrl } from '../src/api/baseUrl';

describe('API base URL normalization', () => {
  it.each([
    ['', ''],
    ['/', ''],
    ['///', ''],
    ['http://192.168.2.10:8000/', 'http://192.168.2.10:8000'],
    ['/gateway///', '/gateway']
  ])('normalizes %j to %j', (input, expected) => {
    expect(normalizeApiBaseUrl(input)).toBe(expected);
  });
});
