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
  deleteOutreachTask,
  FULFILLMENT_STATUS_TRANSITIONS,
  formatInfluencerError,
  OUTREACH_PRIORITY_LABELS,
  restoreOutreachTarget,
  updateOutreachStatus,
  updateOutreachTarget,
  updateOutreachTask,
  updateSampleFulfillmentStatus
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

  it('aligns the outreach workspace with the BD task view and exposes the task detail loop', () => {
    const page = read('src/views/influencers/OutreachTaskList.vue');
    for (const field of ['task_name', 'store', 'external_product_id', 'sku_prefix', 'target_count', 'owner']) expect(page).toContain(field);
    for (const contract of [
      'linked_count',
      'target_count',
      'dispatch_time',
      'started_at',
      '关联达人',
      '查看详情',
      '修改',
      '删除',
      '创建送样',
      'el-drawer',
      '@row-click="openDetail"',
      'fetchOutreachTask',
      'fetchOutreachProgress',
      'fetchSampleFulfillments',
      'updateOutreachTask',
      'deleteOutreachTask'
    ]) expect(page).toContain(contract);
    expect(page).not.toContain('达人目标');
    for (const label of ['全部任务', '进行中', '已建联', '送样记录', '搜索任务/店铺/商品/负责人', '全部状态', '全部店铺', '全部下发人', '正常任务', '任务履约反馈', '目标进度']) expect(page).toContain(label);
    for (const column of ['任务', '店铺 / 商品', '优先级', '负责人', '状态', '任务下发人', '开始时间', '下发时间', '操作']) expect(page).toContain(`label="${column}"`);
    expect(read('src/api/influencers.js')).toContain('黑名单');
    expect(read('src/api/influencers.js')).toContain('终态');
    expect(read('src/api/influencers.js')).toContain("'If-Match'");
    expect(page).toContain('nextTaskStatuses');
    expect(page).toContain('fetchOutreachTaskOptions');
    expect(page).toContain('按店铺名称搜索');
    expect(page).toContain('目标人数');
    expect(page).toContain('按姓名或账号搜索');
    expect(page).toContain('OUTREACH_PRIORITY_LABELS');
    expect(page).toContain("priority: 'normal'");
    expect(page).toContain('filterable');
    expect(page).toContain('influencerOptions');
    for (const field of ['influencer_name', 'influencer_code', 'influencer_platform']) expect(page).toContain(field);
    expect(page).toContain("path: '/influencers/sample-fulfillments'");
    expect(page).toContain('outreach_task: String(activeTask.value.id)');
    expect(page).toContain('outreach_target: String(row.id)');
    expect(page).toContain('matchOutreachProduct');
    expect(page).toContain('商品数据未导入');
    expect(page).toContain('已匹配店铺');
    expect(page).toContain('matchedCandidates.value.forEach');
    expect(page).toContain('matchedStoreIds.value.map');
    expect(page).toContain('params.status = filters.status');
    expect(page).toContain('params.store = filters.store');
    expect(page).toContain('matchesDispatcher');
    expect(page).toContain("row.priority === 'normal'");
    expect(page).toContain('sample_fulfillment_count');
    expect(page).toContain('displayValue(row.notes)');
    expect(page).toContain('<style scoped>');
  });

  it('matches the BD fulfillment columns and keeps the two-column create form contracts', () => {
    const page = read('src/views/influencers/SampleFulfillmentList.vue');
    for (const field of ['form.outreach_task', 'form.outreach_target', 'inheritedTask?.store', 'inheritedTask?.external_product_id', 'requested_sku', 'quantity', 'sample_order_no', 'notes']) expect(page).toContain(field);
    for (const label of ['搜索达人/建联编号/产品/订单', '全部店铺', '全部状态', '新增送样', '建联编号', '任务 ID', '达人', '店铺', '产品 / SKU / 数量', '商品 ID', '样品订单', '成本', '状态', '备注', '建联日期', '操作']) expect(page).toContain(label);
    for (const field of ['送样履约', '新增送样记录', '送样日期', '达人账号', '达人 ID', '产品名称', '产品 ID', '待发样', 'SKU 与数量', '保存送样']) expect(page).toContain(field);
    const dialog = page.slice(page.indexOf('<el-dialog v-model="visible"'));
    const dialogOrder = ['建联任务', '送样日期', '达人账号', '达人 ID', '店铺', '样品订单', '产品名称', '产品 ID', '状态', 'SKU 与数量', '备注'];
    let previous = -1;
    for (const field of dialogOrder) {
      const position = dialog.indexOf(`label="${field}"`);
      expect(position, field).toBeGreaterThan(previous);
      previous = position;
    }
    expect(page).toContain('添加 SKU');
    expect(page).toContain('价格未匹配');
    expect(page).toContain('statusLabel(FULFILLMENT_STATUS_LABELS');
    for (const field of ['sales_amount', 'calculated_cost', 'pricing_status', 'price_match_status', 'cost_match_status']) expect(page).toContain(field);
    expect(page).toContain('PRICING_STATUS_LABELS');
    expect(page).toContain('displayAmount');
    expect(page).toContain("value === null || value === undefined || value === ''");
    expect(page).toContain('FULFILLMENT_STATUS_TRANSITIONS');
    expect(page).toContain('updateSampleFulfillmentStatus');
    expect(page).toContain('outreach_task');
    expect(page).toContain('outreach_target');
    expect(page).toContain('querySelection');
    expect(page).toContain('targetLabel');
    expect(page).toContain('targetAccount(selectedTarget)');
    expect(page).toContain('todayLabel');
    expect(page).toContain('readonly');
    expect(page).toContain('form-grid');
    expect(page).not.toContain('inbound_cost');
    expect(page).not.toContain('unit_cost');
    expect(page).not.toContain('cost_updated_at');
    expect(page).not.toContain('stock');
    expect(page).toContain('draftKey.value = newKey()');
    expect(page).toContain('createSampleFulfillment(payload, draftKey.value)');
    expect(page).toContain('notes: form.notes');
    expect(page).not.toContain('sample_sent_date');
    expect(page).toContain('if (!r.success) return ElMessage.error');
  });

  it('disables target mutations for read-only, terminal tasks, and terminal target results', () => {
    const page = read('src/views/influencers/OutreachTaskList.vue');
    expect(page).toMatch(/:disabled="!canManage \|\| isTerminal\(activeTask\)"/);
    expect(page).toMatch(/:disabled="!canManage \|\| isTerminal\(activeTask\) \|\| isTargetTerminal\(row\)"/);
    expect(page).toContain("['success', 'rejected', 'no_response', 'blocked']");
    expect(page).toContain('await refreshActiveTask()');
  });

  it('keeps priority values and fulfillment transitions aligned with backend contracts', () => {
    expect(OUTREACH_PRIORITY_LABELS).toEqual({ low: '低', normal: '普通', high: '高', urgent: '紧急' });
    expect(Object.keys(OUTREACH_PRIORITY_LABELS)).toEqual(['low', 'normal', 'high', 'urgent']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.pending).toEqual(['processing', 'creating', 'blank', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.processing).toEqual(['shipped', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.shipped).toEqual(['delivered', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.delivered).toEqual(['completed', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.completed).toEqual([]);
    expect(FULFILLMENT_STATUS_TRANSITIONS.cancelled).toEqual([]);

    requestMock.mockReturnValue({ success: true });
    updateSampleFulfillmentStatus(8, 'processing', 2);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/influencers/sample-fulfillments/8/status/',
      data: { status: 'processing' },
      headers: { 'If-Match': '"2"' }
    });
  });

  it('sends exact task detail routes, If-Match CAS headers, restore headers, and idempotency keys', () => {
    requestMock.mockReturnValue({ success: true });
    updateOutreachStatus(7, 'in_progress', 3);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/influencers/outreach-tasks/7/status/',
      headers: { 'If-Match': '"3"' }
    });

    updateOutreachTask(7, { task_name: 'Edited task', target_count: 2 }, 4);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'patch',
      url: '/api/internal/influencers/outreach-tasks/7/',
      data: { task_name: 'Edited task', target_count: 2 },
      headers: { 'If-Match': '"4"' }
    });

    deleteOutreachTask(7);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'delete',
      url: '/api/internal/influencers/outreach-tasks/7/'
    });

    updateOutreachTarget(7, 9, { notes: 'demo' }, 5);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'patch',
      url: '/api/internal/influencers/outreach-tasks/7/targets/9/',
      headers: { 'If-Match': '"5"' }
    });

    deleteOutreachTarget(7, 9, 6);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'delete',
      url: '/api/internal/influencers/outreach-tasks/7/targets/9/',
      headers: { 'If-Match': '"6"' }
    });

    restoreOutreachTarget(7, { id: 9, influencer: 12 }, 7);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/influencers/outreach-tasks/7/targets/',
      data: { influencer: 12 },
      headers: { 'If-Match': '"7"' }
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
