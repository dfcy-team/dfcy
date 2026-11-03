import { describe, expect, it } from 'vitest';
import { formatDocumentTime } from '../src/utils/supplyDocumentTime';

describe('supply document business time', () => {
  it('retains date-only precision and the server business wall-clock time', () => {
    expect(formatDocumentTime('2025-12-04')).toBe('2025-12-04');
    expect(formatDocumentTime('2025-10-08T11:22:08+08:00')).toBe('2025-10-08 11:22:08');
    expect(formatDocumentTime(null)).toBe('—');
  });
});
