import { describe, expect, it } from 'vitest';
import { outreachProgressLabel, requiresCancellationConfirmation, sampleProgressLabel } from './outreachTaskState';

describe('outreach task state presentation', () => {
  it('uses the task completed fulfillment count when progress details omit it', () => {
    expect(outreachProgressLabel(
      { target_count: 2 },
      { target_count: 2, sample_fulfillment_count: 2, sample_fulfillment_completed_count: 1 }
    )).toBe('送样 2/2 · 完成 1/2');
  });

  it('shows created samples separately from effective completions', () => {
    const row = { target_count: 3, sample_fulfillment_count: 3, sample_fulfillment_completed_count: 0 };
    expect(sampleProgressLabel(row)).toBe('3/3');
    expect(outreachProgressLabel(row, row)).toBe('送样 3/3 · 完成 0/3');
  });

  it('requires confirmation only when entering the cancelled terminal state', () => {
    expect(requiresCancellationConfirmation('in_progress', 'cancelled')).toBe(true);
    expect(requiresCancellationConfirmation('in_progress', 'completed')).toBe(false);
    expect(requiresCancellationConfirmation('cancelled', 'cancelled')).toBe(false);
  });
});
