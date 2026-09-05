import { describe, expect, it } from 'vitest';
import { outreachProgressLabel, requiresCancellationConfirmation, sampledInfluencerCount, sampleProgressLabel } from './outreachTaskState';

describe('outreach task state presentation', () => {
  it('uses unique sampled influencers for task progress', () => {
    expect(outreachProgressLabel(
      { target_count: 2 },
      { target_count: 2, sample_fulfillment_count: 3, sample_fulfillment_influencer_count: 2 }
    )).toBe('送样达人 2/2');
  });

  it('falls back to the existing sample count for old VM10 responses', () => {
    const row = { target_count: 3, sample_fulfillment_count: 3, sample_fulfillment_completed_count: 0 };
    expect(sampledInfluencerCount(row)).toBe(3);
    expect(sampleProgressLabel(row)).toBe('3/3');
    expect(outreachProgressLabel(row, row)).toBe('送样达人 3/3');
  });

  it('does not let duplicate identity records inflate creator progress', () => {
    const row = { target_count: 2, sample_fulfillment_count: 2, sample_fulfillment_influencer_count: 1 };
    expect(sampledInfluencerCount(row)).toBe(1);
    expect(sampleProgressLabel(row)).toBe('1/2');
  });

  it('requires confirmation only when entering the cancelled terminal state', () => {
    expect(requiresCancellationConfirmation('in_progress', 'cancelled')).toBe(true);
    expect(requiresCancellationConfirmation('in_progress', 'completed')).toBe(false);
    expect(requiresCancellationConfirmation('cancelled', 'cancelled')).toBe(false);
  });
});
