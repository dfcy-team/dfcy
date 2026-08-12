<template>
  <section class="sample-page">
    <header class="page-hero">
      <div>
        <span>FULFILLMENT DESK</span>
        <h1>送样履约</h1>
        <p>跟踪建联达人从待发样到内容交付的完整履约过程。</p>
      </div>
    </header>

    <div class="metrics">
      <div><span>当前记录</span><strong>{{ displayValue(total) }}</strong></div>
      <div><span>已进入履约</span><strong>{{ displayValue(fulfilledCount) }}</strong></div>
      <div><span>待发样</span><strong>{{ displayValue(pendingCount) }}</strong></div>
      <div><span>异常/取消</span><strong>{{ displayValue(exceptionCount) }}</strong></div>
    </div>

    <el-card class="workspace-card" shadow="never">
      <div class="toolbar">
        <el-input v-model="filters.search" clearable placeholder="搜索达人/建联编号/产品/订单" @keyup.enter="applyFilters" />
        <el-select v-model="filters.store" clearable filterable placeholder="全部店铺">
          <el-option v-for="store in rowStores" :key="store.id" :label="store.name" :value="store.id" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="全部状态">
          <el-option v-for="(label, value) in FULFILLMENT_STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button type="primary" :disabled="!canManage" @click="openCreate">新增送样</el-button>
      </div>

      <el-table v-loading="loading" :data="rows" empty-text="暂无送样履约">
        <el-table-column label="建联编号" min-width="155">
          <template #default="{ row }">
            <b>{{ displayValue(row.outreach_task_no || row.outreach_task) }}</b>
            <small>{{ displayValue(row.outreach_task_name) }}</small>
          </template>
        </el-table-column>
        <el-table-column label="任务 ID" width="100">
          <template #default="{ row }">{{ displayValue(row.outreach_task) }}</template>
        </el-table-column>
        <el-table-column label="达人" min-width="150">
          <template #default="{ row }">
            <b>{{ displayValue(row.influencer_name || row.influencer) }}</b>
            <small v-if="hasValue(row.influencer)">ID {{ row.influencer }}</small>
          </template>
        </el-table-column>
        <el-table-column label="店铺" min-width="130">
          <template #default="{ row }">{{ displayValue(row.store_name || row.store) }}</template>
        </el-table-column>
        <el-table-column label="产品 / SKU / 数量" min-width="220">
          <template #default="{ row }">
            <b>{{ displayValue(row.product_name_snapshot) }}</b>
            <template v-if="row.items?.length">
              <div v-for="item in row.items" :key="item.id || item.requested_sku" class="sku-match">
                <small>{{ displayValue(item.requested_sku || item.matched_sku_code) }} × {{ displayValue(item.quantity) }}</small>
                <div>
                  <el-tag size="small" :type="matchTagType(item.price_match_status)">{{ statusLabel(PRICE_MATCH_STATUS_LABELS, item.price_match_status) }}</el-tag>
                  <el-tag size="small" :type="matchTagType(item.cost_match_status)">{{ statusLabel(COST_MATCH_STATUS_LABELS, item.cost_match_status) }}</el-tag>
                </div>
              </div>
            </template>
            <small v-else>数量 {{ displayValue(row.sku_quantity) }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="external_product_id" label="商品 ID" min-width="155">
          <template #default="{ row }">{{ displayValue(row.external_product_id) }}</template>
        </el-table-column>
        <el-table-column prop="sample_order_no" label="样品订单" min-width="135">
          <template #default="{ row }">{{ displayValue(row.sample_order_no) }}</template>
        </el-table-column>
        <el-table-column label="成本" min-width="125">
          <template #default="{ row }">
            <b>{{ displayAmount(row.calculated_cost, row) }}</b>
            <small v-if="hasValue(row.sales_amount)">销售额 {{ displayAmount(row.sales_amount, row) }}</small>
            <small><el-tag size="small" :type="pricingTagType(row.pricing_status)">{{ statusLabel(PRICING_STATUS_LABELS, row.pricing_status) }}</el-tag></small>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag>{{ statusLabel(FULFILLMENT_STATUS_LABELS, row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">{{ displayValue(row.notes) }}</template>
        </el-table-column>
        <el-table-column label="建联日期" min-width="155">
          <template #default="{ row }">{{ displayValue(outreachDate(row)) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="140" fixed="right">
          <template #default="{ row }">
            <el-dropdown v-if="canManage && nextStatuses(row).length" :disabled="statusUpdatingId === row.id" @command="(nextStatus) => changeStatus(row, nextStatus)">
              <el-button link type="primary">流转</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="nextStatus in nextStatuses(row)" :key="nextStatus" :command="nextStatus">
                    {{ statusLabel(FULFILLMENT_STATUS_LABELS, nextStatus) }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </el-card>

    <el-dialog v-model="visible" class="sample-dialog" width="720px" @closed="discardDraft">
      <template #header>
        <div class="dialog-heading">
          <span>送样履约</span>
          <h2>新增送样记录</h2>
        </div>
      </template>
      <el-form class="sample-form" label-position="top">
        <div class="form-grid">
          <el-form-item label="建联任务" required class="form-span-2">
            <el-select v-model="form.outreach_task" filterable placeholder="请选择建联任务" @change="selectTask">
              <el-option v-for="task in tasks" :key="task.id" :label="`${task.task_name || task.task_no}（${task.task_no}）`" :value="task.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="送样日期">
            <el-input :model-value="todayLabel" readonly />
          </el-form-item>
          <el-form-item label="达人账号" required>
            <el-select v-if="!form.outreach_target" v-model="form.outreach_target" :disabled="!form.outreach_task" filterable placeholder="请选择达人账号">
              <el-option v-for="target in targets" :key="target.id" :label="targetLabel(target)" :value="target.id" />
            </el-select>
            <el-input v-else :model-value="targetAccount(selectedTarget)" readonly />
          </el-form-item>
          <el-form-item label="达人 ID">
            <el-input :model-value="displayValue(selectedTarget?.influencer)" readonly />
          </el-form-item>
          <el-form-item label="店铺">
            <el-input :model-value="displayValue(inheritedTask?.store_name || inheritedTask?.store)" readonly />
          </el-form-item>
          <el-form-item label="样品订单">
            <el-input v-model="form.sample_order_no" placeholder="可填写样品订单号" />
          </el-form-item>
          <el-form-item label="产品名称">
            <el-input :model-value="displayValue(inheritedTask?.product_name_snapshot)" readonly />
          </el-form-item>
          <el-form-item label="产品 ID">
            <el-input :model-value="displayValue(inheritedTask?.external_product_id)" readonly />
          </el-form-item>
          <el-form-item label="状态">
            <el-input model-value="待发样" readonly />
          </el-form-item>
          <el-form-item label="SKU 与数量" class="form-span-2">
            <div class="sku-editor">
              <div class="sku-header"><span>站点</span><span>SKU</span><span>数量</span><span /></div>
              <div v-for="(item, index) in items" :key="index" class="sku-row">
                <el-input v-model="item.site_code" placeholder="站点" />
                <el-input v-model="item.requested_sku" placeholder="SKU 可暂时为空" />
                <el-input-number v-model="item.quantity" :min="1" />
                <el-button link type="danger" :disabled="items.length === 1" @click="items.splice(index, 1)">删除</el-button>
              </div>
              <el-button link type="primary" @click="items.push(newItem())">+ 添加 SKU</el-button>
              <el-alert class="price-note" type="warning" :closable="false" title="价格未匹配不会阻止送样记录保存。" />
            </div>
          </el-form-item>
          <el-form-item label="备注" class="form-span-2">
            <el-input v-model="form.notes" type="textarea" :rows="3" placeholder="填写送样备注" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存送样</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import {
  COST_MATCH_STATUS_LABELS,
  createSampleFulfillment,
  fetchOutreachTask,
  fetchOutreachTargets,
  fetchOutreachTasks,
  fetchSampleFulfillments,
  formatInfluencerError,
  FULFILLMENT_STATUS_LABELS,
  FULFILLMENT_STATUS_TRANSITIONS,
  PRICE_MATCH_STATUS_LABELS,
  PRICING_STATUS_LABELS,
  statusLabel,
  updateSampleFulfillmentStatus
} from '../../api/influencers';
import { collectionRows, collectionTotal, detailData } from '../../utils/businessResponse';

const auth = useAuthStore();
const route = useRoute();
const rows = ref([]);
const tasks = ref([]);
const targets = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const saving = ref(false);
const visible = ref(false);
const inheritedTask = ref(null);
const draftKey = ref('');
const statusUpdatingId = ref(null);
const filters = reactive({ search: '', status: '', store: null });
const form = reactive({ fulfillment_no: '', outreach_task: null, outreach_target: null, sample_order_no: '', notes: '' });
const newItem = () => ({ site_code: 'PH', external_product_id: '', requested_sku: null, quantity: 1 });
const items = ref([newItem()]);
const canManage = computed(() => auth.hasPermission('influencers.fulfillment.manage'));
const fulfilledStatuses = ['shipped', 'delivered', 'received', 'creating', 'published', 'completed', 'live_creator'];
const fulfilledCount = computed(() => rows.value.filter((row) => fulfilledStatuses.includes(row.status) || row.shipped_at || row.sample_order_no).length);
const pendingCount = computed(() => rows.value.filter((row) => row.status === 'pending').length);
const exceptionCount = computed(() => rows.value.filter((row) => ['overdue', 'cancelled'].includes(row.status)).length);
const rowStores = computed(() => [...new Map(rows.value.filter((row) => row.store).map((row) => [row.store, { id: row.store, name: row.store_name || `店铺 ${row.store}` }])).values()]);
const hasValue = (value) => value !== undefined && value !== null && value !== '';
const displayValue = (value) => hasValue(value) ? String(value) : '—';
const selectedTarget = computed(() => targets.value.find((target) => String(target.id) === String(form.outreach_target)) || null);
const todayLabel = (() => {
  const today = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
})();

async function load() {
  loading.value = true;
  const r = await fetchSampleFulfillments({ page: page.value, page_size: pageSize.value, ...filters });
  loading.value = false;
  if (r.success) {
    rows.value = collectionRows(r.data);
    total.value = collectionTotal(r.data);
  } else {
    ElMessage.error(formatInfluencerError(r, '送样列表加载失败'));
  }
}

function applyFilters() {
  page.value = 1;
  load();
}

function resetFilters() {
  Object.assign(filters, { search: '', status: '', store: null });
  applyFilters();
}

const newKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
function discardDraft() { draftKey.value = ''; }

function queryValue(primary, fallback) {
  const value = route.query?.[primary] ?? route.query?.[fallback];
  return Array.isArray(value) ? value[0] : value;
}

function querySelection() {
  return {
    taskId: queryValue('outreach_task', 'task'),
    targetId: queryValue('outreach_target', 'target')
  };
}

async function findTask(taskId) {
  let task = tasks.value.find((item) => String(item.id) === String(taskId));
  if (task) return task;
  const r = await fetchOutreachTask(taskId);
  if (!r.success) return null;
  task = detailData(r.data);
  if (!task.id || ['completed', 'cancelled'].includes(task.status)) return null;
  tasks.value = [task, ...tasks.value];
  return task;
}

async function openCreate(selection = {}) {
  Object.assign(form, {
    fulfillment_no: `SAMPLE-${Date.now()}`,
    outreach_task: null,
    outreach_target: null,
    sample_order_no: '',
    notes: ''
  });
  inheritedTask.value = null;
  targets.value = [];
  items.value = [newItem()];
  draftKey.value = newKey();
  const r = await fetchOutreachTasks({ page: 1, page_size: 100, status: 'in_progress' });
  tasks.value = r.success ? collectionRows(r.data) : [];
  const requested = { ...querySelection(), ...selection };
  if (requested.taskId) {
    const task = await findTask(requested.taskId);
    if (task) {
      form.outreach_task = task.id;
      await selectTask(task.id);
      if (requested.targetId) {
        const target = targets.value.find((item) => String(item.id) === String(requested.targetId));
        if (target) form.outreach_target = target.id;
      }
    }
  }
  visible.value = true;
}

async function selectTask(id) {
  inheritedTask.value = tasks.value.find((item) => String(item.id) === String(id)) || null;
  form.outreach_target = null;
  if (!id) {
    targets.value = [];
    return;
  }
  const r = await fetchOutreachTargets(id, { page: 1, page_size: 100 });
  targets.value = r.success ? collectionRows(r.data) : [];
  if (!r.success) ElMessage.error(formatInfluencerError(r, '关联达人加载失败'));
}

function targetLabel(target) {
  const name = target.influencer_name || target.influencer_code || `达人 ${displayValue(target.influencer)}`;
  const account = [target.influencer_platform, target.influencer_handle].filter(Boolean).join(' · ');
  return account ? `${name}（${account}）` : name;
}

function targetAccount(target) {
  if (!target) return '—';
  const account = [target.influencer_name, target.influencer_code, target.influencer_platform].filter(hasValue).join(' · ');
  return account || displayValue(target.influencer);
}

function outreachDate(row) {
  return row.outreach_at || row.first_linked_at || '—';
}

function displayAmount(value, row) {
  if (value === null || value === undefined || value === '') return '—';
  const currency = row.items?.find((item) => item.currency)?.currency;
  return currency ? `${value} ${currency}` : String(value);
}

function pricingTagType(status) {
  return { full: 'success', partial: 'warning', not_found: 'danger', pending: 'info' }[status] || 'info';
}

function matchTagType(status) {
  if (status === 'matched' || String(status || '').startsWith('matched_')) return 'success';
  if (['pending', 'not_imported'].includes(status)) return 'warning';
  return 'danger';
}

function nextStatuses(row) {
  return FULFILLMENT_STATUS_TRANSITIONS[row?.status] || [];
}

async function changeStatus(row, status) {
  if (!nextStatuses(row).includes(status)) return;
  if (status === 'cancelled') {
    try {
      await ElMessageBox.confirm('取消后不可恢复，确认取消该送样履约吗？', '确认取消', { type: 'warning' });
    } catch {
      return;
    }
  }
  statusUpdatingId.value = row.id;
  try {
    const r = await updateSampleFulfillmentStatus(row.id, status, row.version);
    if (!r.success) {
      ElMessage.error(formatInfluencerError(r));
      if (r.http_status === 409 || r.code === 'STATE_CONFLICT' || r.code === 'CONFLICT') await load();
      return;
    }
    Object.assign(row, detailData(r.data));
    ElMessage.success('送样状态已更新');
  } finally {
    statusUpdatingId.value = null;
  }
}

async function submit() {
  if (!form.fulfillment_no || !form.outreach_task || !form.outreach_target) return ElMessage.warning('请选择任务和达人');
  saving.value = true;
  const payload = {
    fulfillment_no: form.fulfillment_no,
    outreach_task: form.outreach_task,
    outreach_target: form.outreach_target,
    sample_order_no: form.sample_order_no,
    notes: form.notes,
    items: items.value.map((item) => ({
      ...item,
      external_product_id: inheritedTask.value?.external_product_id || '',
      requested_sku: item.requested_sku?.trim() || null
    }))
  };
  const r = await createSampleFulfillment(payload, draftKey.value);
  saving.value = false;
  if (!r.success) return ElMessage.error(formatInfluencerError(r, '送样创建失败'));
  draftKey.value = '';
  visible.value = false;
  ElMessage.success('送样已创建');
  load();
}

onMounted(async () => {
  await load();
  if (canManage.value) {
    const selection = querySelection();
    if (selection.taskId && selection.targetId) await openCreate(selection);
  }
});
</script>

<style scoped>
.sample-page { display: grid; gap: 18px; }
.sample-page .page-hero { display: flex; justify-content: space-between; align-items: end; padding: 24px; border-radius: 16px; background: linear-gradient(120deg, #0b5345, #167d68); color: #fff; }
.page-hero h1 { margin: 6px 0; }
.page-hero p { margin: 0; opacity: .82; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; overflow: hidden; }
.metrics div { padding: 15px 18px; border-right: 1px solid #e5e7eb; }
.metrics div:last-child { border: 0; }
.metrics span, .metrics strong, td small, .sku-match small { display: block; }
.metrics span, td small, .sku-match small { color: #84909c; font-size: 12px; }
.metrics strong { margin-top: 5px; font-size: 24px; color: #1f2937; }
.toolbar { display: flex; flex-wrap: nowrap; align-items: center; gap: 10px; margin-bottom: 16px; overflow-x: auto; }
.toolbar .el-input { flex: 1 1 460px; min-width: 300px; }
.toolbar .el-select { flex: 0 0 145px; width: 145px; }
.toolbar .el-button { flex: 0 0 auto; }
.sku-match { display: grid; gap: 4px; margin-bottom: 6px; }
.sku-match .el-tag + .el-tag { margin-left: 5px; }
.el-pagination { margin-top: 16px; justify-content: flex-end; }
.dialog-heading span { display: block; color: #167d68; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.dialog-heading h2 { margin: 5px 0 0; color: #1f2937; font-size: 22px; }
.sample-form { padding: 0 8px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 18px; }
.form-span-2 { grid-column: 1 / -1; }
.sample-form :deep(.el-form-item) { margin-bottom: 14px; }
.sample-form :deep(.el-form-item__label) { padding-bottom: 5px; color: #374151; font-weight: 600; }
.sample-form :deep(.el-select), .sample-form :deep(.el-input), .sample-form :deep(.el-input-number) { width: 100%; }
.sku-editor { width: 100%; }
.sku-header, .sku-row { display: grid; grid-template-columns: 105px minmax(0, 1fr) 125px 42px; gap: 10px; align-items: center; }
.sku-header { margin-bottom: 6px; color: #84909c; font-size: 12px; }
.sku-row { margin-bottom: 8px; }
.sku-row .el-button { padding: 0; }
.price-note { margin-top: 12px; }
@media (max-width: 760px) {
  .sample-page .page-hero { align-items: stretch; flex-direction: column; gap: 16px; }
  .metrics { grid-template-columns: 1fr 1fr; }
  .toolbar { flex-wrap: wrap; overflow-x: visible; }
  .toolbar .el-input, .toolbar .el-select { flex: 1 1 100%; width: 100%; min-width: 100%; }
  .form-grid { grid-template-columns: 1fr; }
  .form-span-2 { grid-column: auto; }
  .sku-header, .sku-row { grid-template-columns: 1fr; gap: 5px; }
  .sku-header { display: none; }
}
</style>
