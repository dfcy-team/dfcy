import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ElMessageBox } from 'element-plus';
import { ref, watch } from 'vue';

const requestMock = vi.hoisted(() => vi.fn());
const authContext = vi.hoisted(() => ({ canManage: true }));

vi.mock('../src/api/request', () => ({ requestWithMockFallback: requestMock }));
vi.mock('../src/mock/influencers', () => ({ influencerMocks: { list: vi.fn() } }));
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (permission) => permission === 'influencers.manage' && authContext.canManage
  })
}));

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
import { canAccessPath, filterMenuItems, flattenMenuItems, menuItems } from '../src/router/menu';
import InfluencerResourceLibrary from '../src/views/influencers/InfluencerResourceLibrary.vue';
import { creatorHandleFirst } from '../src/views/influencers/creatorLabel';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const tableRows = ref([]);

const resourceLibraryStubs = {
  'el-button': {
    props: { disabled: Boolean, loading: Boolean, type: String },
    emits: ['click'],
    template: '<button :disabled="disabled" :data-type="type" @click="$emit(\'click\', $event)"><slot /></button>'
  },
  'el-card': { template: '<div><slot /></div>' },
  'el-table': {
    props: { data: { type: Array, default: () => [] } },
    setup(props) {
      watch(() => props.data, (data) => { tableRows.value = data; }, { immediate: true });
    },
    template: '<div><slot /></div>'
  },
  'el-table-column': {
    setup() { return { tableRows }; },
    props: { label: String },
    template: '<div class="resource-table-column" :data-label="label"><div v-for="row in tableRows" :key="row.id"><slot :row="row" /></div></div>'
  },
  'el-tag': { template: '<span><slot /></span>' },
  'el-pagination': { template: '<div />' },
  'el-dialog': { props: { modelValue: Boolean }, template: '<div><slot /><slot name="footer" /></div>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<div><slot /></div>' },
  'el-input': {
    props: { modelValue: String },
    emits: ['update:modelValue'],
    template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />'
  },
  'el-select': { props: { modelValue: String }, template: '<select />' },
  'el-option': { template: '<option />' },
  'el-input-number': { props: { modelValue: Number }, template: '<input />' }
};

describe('influencer integration workspace contracts', () => {
  beforeEach(() => {
    requestMock.mockReset();
    authContext.canManage = true;
  });

  it('uses the creator display name before internal codes when the handle is missing', () => {
    expect(creatorHandleFirst({
      influencer_display_name: 'Mutya Catedrilla',
      influencer_code: 'legacy-sample-123'
    })).toBe('Mutya Catedrilla');
  });

  it('rechecks manage permission inside resource mutation handlers', () => {
    const library = read('src/views/influencers/InfluencerResourceLibrary.vue');

    expect(library).toMatch(/function openCreate\(\) \{[^}]*if \(!canManage\.value\) return;[^}]*resetForm\(\);/);
    expect(library).toMatch(/async function save\(\) \{\s+if \(!canManage\.value\) return;\s+if \(!form\.code\.trim\(\)/);
    expect(library).toMatch(/async function changeStatus\(row, status\) \{\s+if \(!canManage\.value\) return;\s+if \(status === 'inactive'\)/);
    expect(library).toContain("import { ElMessage, ElMessageBox } from 'element-plus';");
    expect(library).toContain('停用后将暂不可用于业务操作，可稍后重新启用。确认停用该达人档案吗？');
    expect(library).not.toContain('停用后不可恢复');
    expect(library).toMatch(/if \(status === 'inactive'\) \{[\s\S]+?await ElMessageBox\.confirm\([\s\S]+?\);\s+\} catch \{\s+return;\s+\}\s+\}/);
  });

  it('does not send a status request when deactivation is cancelled', async () => {
    const calls = [];
    requestMock.mockImplementation((config) => {
      calls.push(config);
      return {
        success: true,
        code: 'OK',
        message: 'success',
        data: {
          count: 1,
          results: [{ id: 17, name: 'Demo Creator', code: 'DEMO-17', platform: 'TikTok', status: 'active' }]
        }
      };
    });
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue(new Error('cancelled'));
    const wrapper = mount(InfluencerResourceLibrary, { global: { stubs: resourceLibraryStubs } });

    await flushPromises();
    const callsBeforeStatusChange = calls.length;
    const statusButton = wrapper.findAll('button').find((button) => button.text().includes('停用'));
    await statusButton.trigger('click');
    await flushPromises();

    expect(confirm).toHaveBeenCalled();
    expect(calls).toHaveLength(callsBeforeStatusChange);
    expect(calls.some(({ url }) => url.includes('/status/'))).toBe(false);
    confirm.mockRestore();
  });

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

  it('keeps the resource library focused and exposes BD performance as an independent workspace', () => {
    const hub = read('src/views/influencers/InfluencerList.vue');
    const library = read('src/views/influencers/InfluencerResourceLibrary.vue');
    const api = read('src/api/influencers.js');
    const performance = read('src/views/influencers/BdPerformancePanel.vue');
    const performancePage = read('src/views/influencers/BdPerformance.vue');

    expect(hub).toContain('<InfluencerResourceLibrary />');
    expect(hub).not.toContain('BdPerformancePanel');
    expect(hub).not.toContain('query.tab');
    expect(hub).not.toContain('module-tabs');
    expect(hub).toContain('品牌达人等级资源库');
    expect(library).toContain('新增联系方式');
    expect(library).toContain('allow-create');
    expect(api).toContain("instagram: 'Instagram'");
    expect(api).toContain("line: 'LINE'");
    expect(library).toContain('fetchInfluencers');
    expect(library).toContain('createInfluencer');
    expect(library).toContain('暂无达人档案');
    for (const label of ['等级 / 粉丝', '平均播放', '市场 / 赛道', '首次合作', '合作表现', '历史 GMV', '履约率']) {
      expect(library).toContain(label);
    }
    for (const section of ['身份概览', '内容能力', '合作表现', '联系渠道', '黑名单历史']) {
      expect(library).toContain(section);
    }
    expect(library).toContain('label="达人 ID"');
    expect(library).toContain("profileValue(detail, 'external_influencer_id')");
    expect(library).toContain('label="系统档案编码"');
    expect(library).toContain("profileValue(row, 'external_influencer_id')");
    expect(library).not.toContain('displayValue(row.code)');
    for (const label of ['推荐与合作资源', '推荐商品', '合作店铺', '历史经营指标', '月 GMV', '客单价', '历史 ROI', '视频总播放']) {
      expect(library).toContain(label);
    }
    expect(library).toContain("fetchInfluencer(row.id, { include_relations: 'false' })");
    expect(library).toMatch(/label="平均视频播放"[^\n]+disabled/);
    expect(library).toMatch(/label="平均直播观看"[^\n]+disabled/);
    expect(library).not.toMatch(/function profilePayload\(\)[^\n]+average_video_views/);
    expect(library).toContain("联系方式加载失败，已取消编辑以保护现有数据");
    expect(performancePage).toContain('<h1>BD 绩效</h1>');
    expect(performancePage).toContain('按日期范围查看达人开拓、送样投入与合作产出。');
    expect(performancePage).toContain('<BdPerformancePanel />');
    expect(performance).toContain('fetchBdPerformance');
    expect(performance).toContain('downloadCsv');
    expect(performance).toContain('待预计算');
    expect(performance).not.toMatch(/CN[¥￥]\s*[1-9]/);
  });

  it('registers outreach and fulfillment routes and exposes permission-scoped menu entries', () => {
    const router = read('src/router/index.js');
    const creatorMenu = menuItems.find((item) => item.label === '达人管理');
    const performanceMenu = creatorMenu.children.find((item) => item.path === '/influencers/bd-performance');
    expect(router).toContain("const BdPerformance = () => import('../views/influencers/BdPerformance.vue')");
    expect(router).toContain("path: 'influencers/bd-performance', component: BdPerformance");
    expect(performanceMenu.permissions).toEqual(['influencers.outreach.view', 'influencers.fulfillment.view']);
    expect(performanceMenu.allPermissions).toEqual(['influencers.outreach.view', 'influencers.fulfillment.view']);
    expect(router).toContain("path: 'influencers/outreach-tasks', component: OutreachTaskList");
    expect(router).toContain("path: 'influencers/sample-fulfillments', component: SampleFulfillmentList");

    const outreachUser = { user_type: 'internal', permissions: ['influencers.outreach.view'] };
    const outreachPaths = flattenMenuItems(filterMenuItems(outreachUser)).map((item) => item.path);
    expect(outreachPaths).toContain('/influencers/outreach-tasks');
    expect(outreachPaths).not.toContain('/influencers/bd-performance');
    expect(outreachPaths).not.toContain('/influencers/sample-fulfillments');
    expect(canAccessPath(outreachUser, '/influencers/bd-performance')).toBe(false);
    expect(canAccessPath(outreachUser, '/influencers/outreach-tasks')).toBe(true);
    expect(canAccessPath(outreachUser, '/influencers/sample-fulfillments')).toBe(false);

    const fulfillmentUser = { user_type: 'internal', permissions: ['influencers.fulfillment.view'] };
    const fulfillmentPaths = flattenMenuItems(filterMenuItems(fulfillmentUser)).map((item) => item.path);
    expect(fulfillmentPaths).not.toContain('/influencers/bd-performance');
    expect(canAccessPath(fulfillmentUser, '/influencers/bd-performance')).toBe(false);

    const bothPermissionsUser = {
      user_type: 'internal',
      permissions: ['influencers.outreach.view', 'influencers.fulfillment.view']
    };
    const bothPermissionPaths = flattenMenuItems(filterMenuItems(bothPermissionsUser)).map((item) => item.path);
    expect(bothPermissionPaths).toContain('/influencers/bd-performance');
    expect(canAccessPath(bothPermissionsUser, '/influencers/bd-performance')).toBe(true);
    expect(bothPermissionPaths).toContain('/influencers/outreach-tasks');
    expect(bothPermissionPaths).toContain('/influencers/sample-fulfillments');

    const superuser = { is_superuser: true, user_type: 'internal', permissions: [] };
    const superuserPaths = flattenMenuItems(filterMenuItems(superuser)).map((item) => item.path);
    expect(superuserPaths).toContain('/influencers/bd-performance');
    expect(canAccessPath(superuser, '/influencers/bd-performance')).toBe(true);
  });

  it('aligns the outreach workspace with the BD task view and exposes the task detail loop', () => {
    const page = read('src/views/influencers/OutreachTaskList.vue');
    for (const field of ['task_name', 'store', 'external_product_id', 'sku_prefix', 'target_count', 'owner']) expect(page).toContain(field);
    for (const contract of [
      'linked_count',
      'target_count',
      'dispatch_time',
      'started_at',
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
    for (const column of ['任务', '店铺 / 商品 ID', '优先级', '负责人', '状态', '任务下发人', '开始时间', '下发时间', '操作']) expect(page).toContain(`label="${column}"`);
    expect(read('src/api/influencers.js')).toContain('黑名单');
    expect(read('src/api/influencers.js')).toContain('终态');
    expect(read('src/api/influencers.js')).toContain("'If-Match'");
    expect(page).toContain('nextTaskStatuses');
    expect(page).toContain('fetchOutreachTaskOptions');
    expect(page).toContain("include_influencers: includeInfluencers ? 'true' : 'false'");
    expect(page).toContain('loadTaskOptions(false, true)');
    expect(page).toContain('loadTaskOptions(true, true)');
    expect(page).toContain('按店铺名称搜索');
    expect(page).toContain('目标人数');
    expect(page).toContain('按姓名或账号搜索');
    expect(page).toContain('OUTREACH_PRIORITY_LABELS');
    expect(page).toContain("priority: 'normal'");
    expect(page).toContain('filterable');
    expect(page).toContain('influencerOptions');
    for (const field of ['influencer_name', 'influencer_code', 'influencer_platform']) expect(page).toContain(field);
    expect(page).toContain('openSampleCreate');
    expect(page).toContain('outreach_task: task.id');
    expect(page).toContain('系统自动生成');
    expect(page).not.toContain('if (!form.task_no ||');
    expect(page).toContain('matchOutreachProduct');
    expect(page).toContain('商品数据未匹配');
    expect(page).toContain('已匹配店铺');
    expect(page).toContain('matchedCandidates.value.forEach');
    expect(page).toContain('matchedStoreIds.value.map');
    expect(page).toContain('params.status = filters.status');
    expect(page).toContain('params.store = filters.store');
    expect(page).toContain('matchesDispatcher');
    expect(page).toContain("row.priority === 'normal'");
    expect(page).toContain('sample_fulfillment_count');
    expect(page).toContain('送样记录进度');
    expect(page).toContain('fulfillmentCount(detailTask)');
    expect(page).not.toContain('送样完成校验');
    expect(page).toContain('status: form.status');
    expect(page).toContain('displayValue(row.notes)');
    expect(page).toContain('<style scoped>');
  });

  it('autofills every matched SKU prefix while keeping the task field editable', () => {
    const page = read('src/views/influencers/OutreachTaskList.vue');
    expect(page).toContain('placeholder="匹配商品后自动填写，也可人工调整"');
    expect(page).toContain('applyProductCandidate(form, candidate)');
    expect(page).toContain("candidate.sku_prefixes.join(',')");
    expect(page).not.toContain('v-if="matchedSkuPrefixes.length > 1"');
  });

  it('matches the BD fulfillment columns and keeps the two-column create form contracts', () => {
    const page = read('src/views/influencers/SampleFulfillmentList.vue');
    for (const field of ['form.link_type', 'form.influencer', 'form.store', 'form.external_product_id', 'inheritedTask?.sku_prefix', 'requested_sku', 'quantity', 'sample_order_no', 'notes']) expect(page).toContain(field);
    for (const label of ['搜索达人/送样编号/建联编号/产品/订单', '全部店铺', '全部状态', '新增送样', '送样 / 建联编号', '任务 ID', '达人', '店铺', '产品 / SKU / 数量', '商品 ID', '样品订单', '成本', '状态', '备注', '建联日期', '操作']) expect(page).toContain(label);
    for (const field of ['送样履约', '新增送样记录', '送样日期', '达人账号', '达人 ID', '产品 ID', '待发样', 'SKU 与数量', '保存送样']) expect(page).toContain(field);
    const dialog = page.slice(page.indexOf('<el-dialog v-model="visible"'));
    const dialogOrder = ['送样类型', '送样日期', '达人账号', '达人 ID', '店铺', '样品订单', '产品 ID', '状态', 'SKU 与数量', '备注'];
    let previous = -1;
    for (const field of dialogOrder) {
      const position = dialog.indexOf(`label="${field}"`);
      expect(position, field).toBeGreaterThan(previous);
      previous = position;
    }
    expect(page).toContain('添加 SKU');
    expect(page).toContain('送样编号由系统按类型自动生成');
    expect(page).not.toContain('label="建联任务" required');
    expect(page).toContain('consumeTaskQuery');
    expect(page).toContain('delete query.outreach_task');
    expect(page).not.toContain('label="产品名称" required');
    expect(page).not.toContain('<b>{{ displayValue(row.product_name_snapshot) }}</b>');
    expect(page).toContain('inheritedTask.value.task_name || inheritedTask.value.external_product_id');
    expect(page).toContain('statusLabel(FULFILLMENT_STATUS_LABELS');
    for (const field of ['calculated_cost', 'cost_match_status']) expect(page).toContain(field);
    expect(page).toContain('FULFILLMENT_FILTER_STATUS_LABELS');
    expect(page).toContain("new Set(['processing', 'creating', 'blank', ''])");
    expect(page).toContain('!LEGACY_FULFILLMENT_STATUSES.has(value)');
    expect(page).toContain("!['live_creator', 'blacklisted'].includes(value)");
    expect(page).toContain('placeholder="全部状态" @change="applyFilters"');
    expect(page).toContain('MANUAL_FULFILLMENT_STATUS_LABELS');
    expect(page).toContain("completed: FULFILLMENT_STATUS_LABELS.completed");
    expect(page).toContain("cancelled: FULFILLMENT_STATUS_LABELS.cancelled");
    expect(page).not.toContain(".filter((value) => value !== 'shipped')");
    expect(page).toContain("status: ''");
    expect(page).toContain("...(form.status ? { status: form.status } : {})");
    for (const field of ['calculated_cost', 'cost_match_status', 'COST_MATCH_STATUS_LABELS', 'costMatchLabel']) expect(page).toContain(field);
    for (const field of ['sales_amount', 'pricing_status', 'priced_at', 'unit_price', 'unit_cost', 'currency', 'price_match_status', 'price_source', 'price_snapshot_at']) expect(page).not.toContain(field);
    expect(page).not.toContain('PRICING_STATUS_LABELS');
    expect(page).not.toContain('displayAmount');
    expect(page).toContain('fulfillment-note');
    expect(page).not.toContain('updateSampleFulfillmentStatus');
    expect(page).toContain('ElMessageBox.confirm');
    expect(page).toContain('confirm_terminal');
    expect(page).toContain('status: form.status');
    expect(page).not.toContain("'直播达人'");
    expect(page).not.toContain("'已拉黑'");
    expect(page).toContain('outreach_task');
    expect(page).toContain('influencer: form.influencer');
    expect(page).not.toContain('outreach_target: form.outreach_target');
    expect(page).toContain('querySelection');
    expect(page).toContain('influencerLabel');
    expect(page).toContain('selectedInfluencer?.id');
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
    expect(page).toContain(':disabled="!canCreateFulfillment || isCancelled(detailTask)"');
    expect(page).toContain('isCancelled(task)');
  });

  it('keeps priority values and fulfillment transitions aligned with backend contracts', () => {
    expect(OUTREACH_PRIORITY_LABELS).toEqual({ low: '低', normal: '普通', high: '高', urgent: '紧急' });
    expect(Object.keys(OUTREACH_PRIORITY_LABELS)).toEqual(['low', 'normal', 'high', 'urgent']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.pending).toEqual(['completed', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.processing).toEqual(['completed', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.shipped).toEqual(['completed', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.delivered).toEqual(['completed', 'cancelled']);
    expect(FULFILLMENT_STATUS_TRANSITIONS.completed).toEqual([]);
    expect(FULFILLMENT_STATUS_TRANSITIONS.cancelled).toEqual([]);

    requestMock.mockReturnValue({ success: true });
    updateSampleFulfillmentStatus(8, 'completed', 2);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'post',
      url: '/api/internal/influencers/sample-fulfillments/8/status/',
      data: { status: 'completed' },
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

    deleteOutreachTask(7, 8);
    expect(requestMock.mock.calls.at(-1)[0]).toMatchObject({
      method: 'delete',
      url: '/api/internal/influencers/outreach-tasks/7/',
      headers: { 'If-Match': '"8"' }
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
    expect(formatInfluencerError({ http_status: 400, message: 'Blacklisted influencers cannot receive samples.' })).toBe('该达人已被加入黑名单，不能执行本次操作。');
    expect(formatInfluencerError({ http_status: 409, message: 'Completed outreach tasks cannot change targets.' })).toContain('终态');
    expect(formatInfluencerError({ http_status: 409, message: 'Workflow record was changed by another request.' })).toContain('409');
  });
});
