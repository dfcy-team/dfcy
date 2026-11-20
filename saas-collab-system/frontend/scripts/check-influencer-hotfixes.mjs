import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// Normal builds must include source implementations, not depend on live import maps.
export function checkInfluencerHotfixes(root) {
  const required = {
    'frontend/src/views/influencers/OutreachTaskList.vue': [
      "import PriorityTaskCarousel from './PriorityTaskCarousel.vue'", '<PriorityTaskCarousel ', "priority_only: 'true'",
      'async function openDetail(', 'detailVisible.value = true',
    ],
    'frontend/src/views/influencers/PriorityTaskCarousel.vue': ['上一条重点任务', '下一条重点任务', 'class="task"'],
    'frontend/src/views/influencers/InfluencerRequirements.vue': ['type="file"', 'new FormData()', "data.append('images'", 'fetchApiFile('],
    'backend/apps/influencers/requirement_feedback.py': ['class InfluencerRequirementImageView', 'scoped_requirements(request.user)', 'transaction.atomic()', 'image_content(upload)'],
    'backend/apps/influencers/views.py': ['"priority_only"', '"priority_tasks"'],
    'backend/apps/influencers/migrations/0051_requirement_images.py': ['InfluencerRequirementImage'],
  };
  for (const [name, markers] of Object.entries(required)) {
    const source = readFileSync(resolve(root, name), 'utf8');
    for (const marker of markers) if (!source.includes(marker)) throw new Error(`Hotfix preservation failed: ${name} missing ${marker}`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  checkInfluencerHotfixes(fileURLToPath(new URL('../../', import.meta.url)));
  console.log('Influencer source hotfix preservation checks passed.');
}
