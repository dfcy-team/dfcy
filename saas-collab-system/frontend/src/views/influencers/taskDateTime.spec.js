import { describe, expect, it } from 'vitest';

import { formatTaskDateTime } from './taskDateTime';

describe('formatTaskDateTime', () => {
  it('formats UTC timestamps in Asia/Shanghai', () => {
    expect(formatTaskDateTime('2026-08-20T07:41:19.787064Z')).toBe('2026-08-20 15:41:19');
  });

  it('keeps empty and invalid values readable', () => {
    expect(formatTaskDateTime(null)).toBe('—');
    expect(formatTaskDateTime('not-a-date')).toBe('not-a-date');
  });
});
