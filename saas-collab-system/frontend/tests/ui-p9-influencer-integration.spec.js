import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const requestMock = vi.hoisted(() => vi.fn());

vi.mock('../src/api/request', () => ({ requestWithMockFallback: requestMock }));
vi.mock('../src/mock/influencers', () => ({ influencerMocks: { list: vi.fn() } }));

import {
  addOutreachTarget,
  createSampleFulfillment,
  deleteOutreachTarget,
  formatInfluencerError,
  restoreOutreachTarget,
  updateOutreachStatus,
  updateOutreachTarget
} from '../src/api/influencers';
import { canAccessPath, filterMenuItems, flattenMenuItems } from '../src/router/menu';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('influencer integration workspace contracts', () => {
  beforeEach(() => requestMock.mockReset());

  it('requests and renders pagination on all influencer workspaces', () => {
    for (const path of [
      'src/views/influencers/InfluencerResourceLibrary.vue',
      'src/views/influencers/OutreachTaskList.vue',
      'src/views/influencers/SampleFulfillmentList.vue'
    ]) {
      const source = read(path);
      expect(source, path).toContain('v-model:current-page="page"');
      expect(source, path).toContain('v-model:page-size="pageSize"');
      expect(source, path).toMatch(/page:\s*page\.value,\s*page_size:\s*pageSize\.value/);
      expect(source, path).toContain('collectionTotal');
    }
  });

  it('registers outreach and fulfillment routes and exposes permission-scoped menu entries', () => {
    const router = read('src/router/index.js');
    expect(router).toContain("path: 'influencers/outreach-tasks', component: OutreachTaskList");
    expect(router).toContain("path: 'influencers/sample-fulfillments', component: SampleFulfillmentList");

    const outreachUser = { user_type: 'internal', permissions: ['influencers.outreach.view'] };
    const paths = flattenMenuItems(filterMenuItems(outreachUser)).map((item) => item.path);
    expect(paths).toContain('/influencers/outreach-tasks');
    expect(paths).not.toContain('/influencers/sample-fulfillments');
    expect(canAccessPath(outreachUser, '/influencers/outreach-tasks')).toBe(true);
    expect(canAccessPath(outreachUser, '/influencers/sample-fulfillments')).toBe(false);
  });

  it('keeps task creation, progress, detail target and action contracts visible', () => {
    const page = read('src/views/influencers/OutreachTaskList.vue');
    for (const field of ['task_name', 'store', 'external_product_id', 'sku_prefix', 'target_count', 'owner']) expect(page).toContain(field);
    for (const contract of ['linked_count', 'target_count', 'dispatch_time', 'started_at', 'finalized_at', '添加达人目标', '删除', '恢复']) expect(page).toContain(contract);
    expect(read('src/api/influencers.js')).toContain('黑名单');
    expect(read('src/api/influencers.js')).toContain('终态');
    expect(page).toContain("row.status !== 'pending'");
    expect(page).toContain("row.status !== 'in_progress'");
    expect(page).toContain('fetchOutreachTaskOptions');
    expect(page).toContain('按店铺名称搜索');
    expect(page).toContain('目标建联人数');
    expect(page).toContain('按姓名或账号搜索');
  });

  it('requires task and target selection, supports multiple nullable-SKU rows, and labels missing prices', () => {
    const page = read('src/views/influencers/SampleFulfillmentList.vue');
    for (const field of ['form.outreach_task', 'form.outreach_target', 'inheritedTask.store', 'inheritedTask.external_product_id', 'inheritedTask.owner', 'requested_sku', 'quantity', 'sample_order_no']) expect(page).toContain(field);
    expect(page).toContain('添加 SKU 行');
    expect(page).toContain('价格未导入');
    expect(page).toContain('statusLabel(FULFILLMENT_STATUS_LABELS');
    expect(page).not.toContain('inbound_cost');
    expect(page).not.toContain('unit_cost');
    expect(page).not.toContain('cost_updated_at');
    expect(page).not.toContain('stock');
    expect(page).toContain('draftIdempotencyKey.value=newDraftKey()');
    expect(page).toContain('createSampleFulfillment(payload,draftIdempotencyKey.value)');
    expect(page).toContain("if(!r.success)return ElMessage.error");
  });

  it('disables target mutations for read-only, terminal tasks, and terminal target results', () => {
    const page = read('src/views/influencers/OutreachTaskList.vue');
    expect(page).toContain(':disabled="!canManage||isTerminal(activeTask)"');
    expect(page).toContain(':disabled="!canManage||isTerminal(activeTask)||isTargetTerminal(row)"');
    expect(page).toContain("['success','rejected','no_response','blocked']");
    expect(page).toContain('await refreshActiveTask()');
  });

  it('sends exact backend routes, If-Match CAS headers, restore headers, and idempotency keys', () => {
    requestMock.mockReturnValue({ success: true });
    updateOutreachStatus(7, 'in_progress', 3);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/influencers/outreach-tasks/7/status/',
      headers: { 'If-Match': '"3"' }
    });

    updateOutreachTarget(7, 9, { notes: 'demo' }, 4);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'patch',
      url: '/api/internal/influencers/outreach-tasks/7/targets/9/',
      headers: { 'If-Match': '"4"' }
    });

    deleteOutreachTarget(7, 9, 5);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'delete',
      url: '/api/internal/influencers/outreach-tasks/7/targets/9/',
      headers: { 'If-Match': '"5"' }
    });

    restoreOutreachTarget(7, { id: 9, influencer: 12 }, 6);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/influencers/outreach-tasks/7/targets/',
      data: { influencer: 12 },
      headers: { 'If-Match': '"6"' }
    });

    createSampleFulfillment({ outreach_task: 7, outreach_target: 9 }, 'draft-key');
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/influencers/sample-fulfillments/',
      headers: { 'Idempotency-Key': 'draft-key' }
    });
  });

  it('turns backend blacklist, terminal, and stale-version conflicts into actionable Chinese feedback', () => {
    expect(formatInfluencerError({ http_status: 409, message: 'Blacklisted influencers cannot be linked.' })).toContain('黑名单');
    expect(formatInfluencerError({ http_status: 409, message: 'Completed outreach tasks cannot change targets.' })).toContain('终态');
    expect(formatInfluencerError({ http_status: 409, message: 'Workflow record was changed by another request.' })).toContain('409');
  });
});
