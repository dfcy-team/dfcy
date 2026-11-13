import { describe, expect, it } from 'vitest';
import { capabilityLabel } from '../src/utils/integrationCapabilityLabels';

describe('collection capability labels', () => {
  it('shows a Chinese video name without changing the capability code', () => {
    expect(capabilityLabel('VIDEO')).toBe('VIDEO · 视频');
  });

  it('shows the creator name', () => {
    expect(capabilityLabel('CREATOR')).toBe('CREATOR · 达人');
  });

  it('preserves existing labels and the unknown-code fallback', () => {
    expect(capabilityLabel('PRODUCT')).toBe('PRODUCT · 商品');
    expect(capabilityLabel('UNKNOWN')).toBe('UNKNOWN · UNKNOWN');
  });
});
