import { describe, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkInfluencerHotfixes } from '../scripts/check-influencer-hotfixes.mjs';

const frontendSource = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backendSource = resolve(frontendSource, '../backend');
const sourceFiles = [
  ['frontend', 'src/views/influencers/OutreachTaskList.vue'],
  ['frontend', 'src/views/influencers/PriorityTaskCarousel.vue'],
  ['frontend', 'src/views/influencers/InfluencerRequirements.vue'],
  ['backend', 'apps/influencers/requirement_feedback.py'],
  ['backend', 'apps/influencers/views.py'],
  ['backend', 'apps/influencers/migrations/0049_requirement_images.py'],
];

function fixture(layout) {
  const root = mkdtempSync(resolve(tmpdir(), 'influencer-gate-'));
  const frontendRoot = resolve(root, layout === 'docker' ? 'app' : 'frontend');
  const backendRoot = resolve(root, 'backend');
  mkdirSync(root, { recursive: true });
  for (const [area, name] of sourceFiles) {
    const source = resolve(area === 'frontend' ? frontendSource : backendSource, name);
    const target = resolve(area === 'frontend' ? frontendRoot : backendRoot, name);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, readFileSync(source));
  }
  return { root, frontendRoot, backendRoot };
}

describe('formal source hotfix preservation', () => {
  it('accepts the monorepo frontend/ + backend/ mapping', () => {
    const roots = { frontendRoot: frontendSource, backendRoot: backendSource };
    expect(() => checkInfluencerHotfixes(roots)).not.toThrow();
  });

  it('accepts flattened Docker /app + /backend mapping and rejects carousel and image regressions', () => {
    const roots = fixture('docker');
    try {
      expect(roots.frontendRoot).toMatch(/[\\/]app$/);
      expect(roots.backendRoot).toMatch(/[\\/]backend$/);
      expect(() => checkInfluencerHotfixes(roots)).not.toThrow();

      const carouselPage = resolve(roots.frontendRoot, 'src/views/influencers/OutreachTaskList.vue');
      const carouselSource = readFileSync(carouselPage, 'utf8');
      writeFileSync(carouselPage, carouselSource.replace('<PriorityTaskCarousel ', '<RemovedCarousel '));
      expect(() => checkInfluencerHotfixes(roots)).toThrow('Hotfix preservation failed');
      writeFileSync(carouselPage, carouselSource);

      const imagePage = resolve(roots.frontendRoot, 'src/views/influencers/InfluencerRequirements.vue');
      const imageSource = readFileSync(imagePage, 'utf8');
      writeFileSync(imagePage, imageSource.replace("data.append('images'", "data.append('removed'"));
      expect(() => checkInfluencerHotfixes(roots)).toThrow('Hotfix preservation failed');
      writeFileSync(imagePage, imageSource);

      const imageMigration = resolve(roots.backendRoot, 'apps/influencers/migrations/0049_requirement_images.py');
      const migrationSource = readFileSync(imageMigration, 'utf8');
      writeFileSync(imageMigration, migrationSource.replace('InfluencerRequirementImage', 'RemovedImageModel'));
      expect(() => checkInfluencerHotfixes(roots)).toThrow('Hotfix preservation failed');
    } finally {
      if (dirname(roots.root) !== resolve(tmpdir()) || !basename(roots.root).startsWith('influencer-gate-')) throw new Error('Unsafe fixture cleanup path');
      rmSync(roots.root, { recursive: true });
    }
  });
});
