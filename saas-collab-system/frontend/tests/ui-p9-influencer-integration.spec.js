import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('influencer integration workspace contracts', () => {
  const pages = [
    'src/views/influencers/InfluencerResourceLibrary.vue',
    'src/views/influencers/OutreachTaskList.vue',
    'src/views/influencers/SampleFulfillmentList.vue',
  ];

  it('requests and renders pagination on all three influencer pages', () => {
    for (const path of pages) {
      const source = read(path);
      expect(source, path).toContain('v-model:current-page="page"');
      expect(source, path).toContain('v-model:page-size="pageSize"');
      expect(source, path).toContain('page:page.value,page_size:pageSize.value');
      expect(source, path).toContain('collectionTotal');
    }
  });

  it('does not render cost or stock fields in the fulfillment workspace', () => {
    const source = read('src/views/influencers/SampleFulfillmentList.vue');
    for (const field of ['inbound_cost', 'unit_cost', 'cost_updated_at', 'stock']) {
      expect(source).not.toContain(`prop="${field}"`);
    }
  });

  it('keeps a draft idempotency key across retries and only enables completion in progress', () => {
    const fulfillment = read('src/views/influencers/SampleFulfillmentList.vue');
    const outreach = read('src/views/influencers/OutreachTaskList.vue');
    expect(fulfillment).toContain("draftRequestKey=ref('')");
    expect(fulfillment).toContain('function openDialog()');
    expect(fulfillment).toContain('const key=draftRequestKey.value||');
    expect(fulfillment).toContain('createSampleFulfillment({...form,items},key)');
    expect(outreach).toContain("row.status!=='in_progress'");
  });
});
