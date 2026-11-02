import { test } from 'vitest';
import assert from 'node:assert/strict';
import { advertisingRatio } from '../src/utils/advertisingRatio.js';

test('display ratios use aggregate inputs rather than adding campaign ratios', () => {
  assert.equal(advertisingRatio('177.51', '28.15'), '6.31');
  assert.equal(advertisingRatio('28.15', 20), '1.41');
  assert.equal(advertisingRatio('0', '10'), '0.00');
});
test('unknown and zero denominators are not fabricated zero performance', () => {
  assert.equal(advertisingRatio(null, 1), '未知');
  assert.equal(advertisingRatio('', 1), '未知');
  for (const d of [0, -1, 'invalid', Infinity]) assert.equal(advertisingRatio(1, d), '—');
});
