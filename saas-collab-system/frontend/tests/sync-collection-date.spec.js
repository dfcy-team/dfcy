import { expect, it } from 'vitest';
import { syncCollectionDate, syncTime } from '../src/utils/syncPresentation';

it('correctly renders historical second timestamps without changing milliseconds or ISO dates', () => {
  for (const value of [1788321143, 1788321143000, '2026-09-02T03:52:23Z']) {
    expect(syncTime(value)).toBe('2026-09-02 03:52:23');
  }
  expect(syncTime(null)).toBe('—');
});

it('shows collection days in Beijing time including its midnight boundary', () => {
  expect(syncCollectionDate(1788321143)).toBe('2026-09-02');
  expect(syncCollectionDate(Date.parse('2026-09-16T16:00:00Z') / 1000)).toBe('2026-09-17');
  expect(syncCollectionDate(null)).toBe('—');
  expect(syncCollectionDate('invalid')).toBe('—');
});
