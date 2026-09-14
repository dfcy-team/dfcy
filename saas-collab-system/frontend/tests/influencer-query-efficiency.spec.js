import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';


const read = (path) => readFileSync(`${process.cwd()}/${path}`, 'utf8');


describe('influencer query efficiency', () => {
  it('loads archive detail with one aggregate detail request', () => {
    const page = read('src/views/influencers/InfluencerResourceLibrary.vue');

    expect(page).toContain('const profileResponse = await fetchInfluencer(row.id)');
    expect(page).not.toContain('fetchInfluencerContacts,');
    expect(page).not.toContain('fetchInfluencerBlacklistHistory,');
  });

  it('filters fulfillment detail by the task foreign key', () => {
    const page = read('src/views/influencers/OutreachTaskList.vue');

    expect(page).toContain('fetchSampleFulfillments({ outreach_task: taskId');
    expect(page).not.toContain('fetchSampleFulfillments({ search: task.task_no');
  });
});
