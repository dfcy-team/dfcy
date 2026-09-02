import { describe, expect, it } from 'vitest';
import { outreachProgressLabel, requiresCancellationConfirmation } from './outreachTaskState';

describe('outreach task state presentation', () => {
  it('uses the task completed fulfillment count when progress details omit it', () => {
    expect(outreachProgressLabel(
      { target_count: 2 },
      { target_count: 2, sample_fulfillment_completed_count: 1 }
    )).toBe('1/2');
  });

  it('requires confirmation only when entering the cancelled terminal state', () => {
    expect(requiresCancellationConfirmation('in_progress', 'cancelled')).toBe(true);
    expect(requiresCancellationConfirmation('in_progress', 'completed')).toBe(false);
    expect(requiresCancellationConfirmation('cancelled', 'cancelled')).toBe(false);
  });
});
