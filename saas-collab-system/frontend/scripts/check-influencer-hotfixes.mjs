import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// Normal builds must include source implementations, not depend on live import maps.
export function checkInfluencerHotfixes({ frontendRoot, backendRoot }) {
  const required = [
    [frontendRoot, 'src/views/influencers/OutreachTaskList.vue', [
      "import PriorityTaskCarousel from './PriorityTaskCarousel.vue'", '<PriorityTaskCarousel ', "priority_only: 'true'",
      'async function openDetail(', 'detailVisible.value = true',
    ]],
    [frontendRoot, 'src/views/influencers/PriorityTaskCarousel.vue', ['上一条重点任务', '下一条重点任务', 'class="task"']],
    [frontendRoot, 'src/views/influencers/InfluencerRequirements.vue', ['type="file"', 'new FormData()', "data.append('images'", 'fetchApiFile(']],
    [backendRoot, 'apps/influencers/requirement_feedback.py', ['class InfluencerRequirementImageView', 'scoped_requirements(request.user)', 'transaction.atomic()', 'image_content(upload)']],
    [backendRoot, 'apps/influencers/views.py', ['"priority_only"', '"priority_tasks"']],
    [backendRoot, 'apps/influencers/migrations/0049_requirement_images.py', ['InfluencerRequirementImage']],
  ];
  for (const [base, name, markers] of required) {
    const source = readFileSync(resolve(base, name), 'utf8');
    for (const marker of markers) if (!source.includes(marker)) throw new Error(`Hotfix preservation failed: ${name} missing ${marker}`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const frontendRoot = resolve(fileURLToPath(new URL('../', import.meta.url)));
  const backendRoot = resolve(frontendRoot, '../backend');
  checkInfluencerHotfixes({ frontendRoot, backendRoot });
  console.log('Influencer source hotfix preservation checks passed.');
}
