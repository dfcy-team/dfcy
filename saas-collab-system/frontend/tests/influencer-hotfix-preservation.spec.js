import { describe, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { checkInfluencerHotfixes } from '../scripts/check-influencer-hotfixes.mjs';

describe('formal source hotfix preservation', () => {
  it('accepts integrated source and blocks a missing carousel or image implementation', () => {
    const root = resolve(process.cwd(), '..');
    expect(() => checkInfluencerHotfixes(root)).not.toThrow();
    const fixture = mkdtempSync(resolve(tmpdir(), 'influencer-gate-'));
    try {
      for (const name of [
        'frontend/src/views/influencers/OutreachTaskList.vue',
        'frontend/src/views/influencers/PriorityTaskCarousel.vue',
        'frontend/src/views/influencers/InfluencerRequirements.vue',
        'backend/apps/influencers/requirement_feedback.py', 'backend/apps/influencers/views.py',
        'backend/apps/influencers/migrations/0049_requirement_images.py',
      ]) {
        const target = resolve(fixture, name);
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, readFileSync(resolve(root, name)));
      }
      const page = resolve(fixture, 'frontend/src/views/influencers/OutreachTaskList.vue');
      writeFileSync(page, readFileSync(page, 'utf8').replace('<PriorityTaskCarousel ', '<RemovedCarousel '));
      expect(() => checkInfluencerHotfixes(fixture)).toThrow('Hotfix preservation failed');
    } finally { rmSync(fixture, { recursive: true }); }
  });
});
