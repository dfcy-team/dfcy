<template>
  <AppPage
    eyebrow="SC-F1 · LOCAL DEVELOPMENT"
    title="供应链采购协同"
    subtitle="管理采购单头、明细、供应商接单和生产进度。"
    boundary-note="当前能力仅用于架构员主机的本地 MySQL / Mock 开发；不连接线上 Supabase，不迁移生产数据，不发送真实通知。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="canCreate" type="primary" @click="openCreate">新建供应链采购单</el-button>
    </template>

    <section class="summary-grid" aria-label="供应链采购概览">
      <article>
        <span>当前范围</span>
        <strong>{{ total }}</strong>
        <small>张采购单</small>
      </article>
      <article>
        <span>待接单</span>
        <strong>{{ statusCount('pending') }}</strong>
        <small>等待供应商确认</small>
      </article>
      <article>
        <span>生产中</span>
        <strong>{{ statusCount('in_production') }}</strong>
        <small>持续回填进度</small>
      </article>
      <article>
        <span>生产完成</span>
        <strong>{{ statusCount('production_completed') }}</strong>
        <small>物流阶段尚未开放</small>
      </article>
    </section>

    <p class="page-scope-note">状态卡按当前页统计；“当前范围”显示筛选后的全部记录数。</p>

    <section class="filter-bar">
      <el-input v-model="filters.search" clearable placeholder="采购单号 / 供应商" aria-label="采购单搜索" />
      <el-select v-model="filters.status" clearable placeholder="全部状态" aria-label="状态筛选">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-button type="primary" plain @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />

    <el-table v-else :data="rows" border stripe>
      <el-table-column label="采购单号" min-width="180" fixed="left">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">{{ row.order_no }}</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="supplier_name" label="供应商" min-width="180" />
      <el-table-column label="状态" width="126">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="line_count" label="明细行" width="88" align="center" />
      <el-table-column prop="total_quantity" label="采购数量" width="105" align="right" />
      <el-table-column label="生产进度" min-width="170">
        <template #default="{ row }">
          <el-progress :percentage="progressPercent(row)" :stroke-width="7" />
        </template>
      </el-table-column>
      <el-table-column prop="expected_delivery_date" label="预计交期" width="120" />
      <el-table-column label="操作" min-width="330" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button
            v-if="row.status === 'pending' && canAccept"
            size="small"
            type="primary"
            @click="runAction(row, 'accept')"
          >
            接单
          </el-button>
          <el-button
            v-if="row.status === 'accepted' && canStart"
            size="small"
            type="primary"
            @click="runAction(row, 'start-production')"
          >
            开始生产
          </el-button>
          <el-button
            v-if="row.status === 'in_production' && canUpdate"
            size="small"
            @click="openProgress(row)"
          >
            更新进度
          </el-button>
          <el-button
            v-if="row.status === 'in_production' && canComplete"
            size="small"
            type="success"
            :disabled="Number(row.completed_quantity) !== Number(row.total_quantity)"
            @click="runAction(row, 'complete-production')"
          >
            生产完成
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-if="state === 'ready' && total > 0"
      class="pagination"
      background
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
      :current-page="pagination.page"
      :page-size="pagination.pageSize"
      :page-sizes="[10, 20, 50, 100]"
      @current-change="changePage"
      @size-change="changePageSize"
    />

    <el-drawer v-model="detailOpen" title="供应链采购单详情" size="min(820px, 96vw)">
      <template v-if="selected">
        <div class="drawer-heading">
          <div>
            <small>{{ selected.supplier_code }} · {{ selected.supplier_name }}</small>
            <h2>{{ selected.order_no }}</h2>
          </div>
          <el-tag :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag>
        </div>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="采购日期">{{ selected.order_date }}</el-descriptions-item>
          <el-descriptions-item label="预计交期">{{ selected.expected_delivery_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="采购数量">{{ selected.total_quantity }}</el-descriptions-item>
          <el-descriptions-item label="已完成">{{ selected.completed_quantity }}</el-descriptions-item>
          <el-descriptions-item label="币种">{{ selected.currency }}</el-descriptions-item>
          <el-descriptions-item label="版本">v{{ selected.version }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ selected.notes || '-' }}</el-descriptions-item>
        </el-descriptions>

        <h3>采购明细</h3>
        <el-table :data="selected.lines || []" border>
          <el-table-column prop="line_no" label="行号" width="70" />
          <el-table-column prop="sku_code_snapshot" label="SKU" min-width="140" />
          <el-table-column prop="product_name_snapshot" label="商品" min-width="180" />
          <el-table-column prop="quantity" label="数量" width="90" align="right" />
          <el-table-column prop="unit_price" label="本币单价" width="110" align="right" />
          <el-table-column prop="expected_delivery_date" label="交期" width="120" />
        </el-table>

        <h3>生产进度记录</h3>
        <el-timeline v-if="selected.progress_entries?.length">
          <el-timeline-item
            v-for="entry in selected.progress_entries"
            :key="entry.id"
            :timestamp="formatTime(entry.created_at)"
          >
            完成 {{ entry.completed_quantity }}（{{ entry.progress_percent }}%）
            <span v-if="entry.note"> · {{ entry.note }}</span>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="尚无生产进度记录" />
      </template>
    </el-drawer>

    <el-dialog v-model="createOpen" title="新建供应链采购单" width="min(720px, 94vw)">
      <el-alert
        title="首批开发只支持已存在的供应商主档和 SKU；输入 ID 必须属于当前租户。"
        type="info"
        :closable="false"
      />
      <el-form label-position="top" class="dialog-form">
        <div class="form-grid">
          <el-form-item label="采购单号"><el-input v-model="createForm.order_no" /></el-form-item>
          <el-form-item label="供应商主档 ID"><el-input-number v-model="createForm.supplier_id" :min="1" /></el-form-item>
          <el-form-item label="采购日期"><el-input v-model="createForm.order_date" placeholder="YYYY-MM-DD" /></el-form-item>
          <el-form-item label="预计交期"><el-input v-model="createForm.expected_delivery_date" placeholder="YYYY-MM-DD" /></el-form-item>
          <el-form-item label="SKU ID"><el-input-number v-model="createForm.sku_id" :min="1" /></el-form-item>
          <el-form-item label="数量"><el-input-number v-model="createForm.quantity" :min="1" /></el-form-item>
          <el-form-item label="单价"><el-input v-model="createForm.unit_price" /></el-form-item>
          <el-form-item label="币种"><el-input v-model="createForm.currency" maxlength="8" /></el-form-item>
          <el-form-item label="备注" class="form-span"><el-input v-model="createForm.notes" type="textarea" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">保存到本地</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="progressOpen" title="更新生产进度" width="min(520px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="已完成数量">
          <el-input-number
            v-model="progressForm.completed_quantity"
            :min="Number(progressTarget?.completed_quantity || 0)"
            :max="Number(progressTarget?.total_quantity || 0)"
          />
        </el-form-item>
        <el-form-item label="进度说明"><el-input v-model="progressForm.note" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="progressOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitProgress">提交进度</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import {
  createSupplyOrder,
  fetchSupplyOrder,
  fetchSupplyOrders,
  runSupplyOrderAction
} from '../../api/supplyChain';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const rows = ref([]);
const total = ref(0);
const state = ref('loading');
const capability = ref('pending');
const errorMessage = ref('');
const detailOpen = ref(false);
const createOpen = ref(false);
const progressOpen = ref(false);
const selected = ref(null);
const progressTarget = ref(null);
const submitting = ref(false);
const filters = reactive({ search: '', status: '' });
const pagination = reactive({ page: 1, pageSize: 20 });
const createForm = reactive({
  order_no: '',
  supplier_id: 1,
  order_date: '2026-07-25',
  expected_delivery_date: '',
  sku_id: 1,
  quantity: 1,
  unit_price: '0.0000',
  currency: 'CNY',
  notes: ''
});
const progressForm = reactive({ completed_quantity: 0, note: '' });

const statusOptions = [
  { value: 'pending', label: '待接单' },
  { value: 'accepted', label: '已接单' },
  { value: 'in_production', label: '生产中' },
  { value: 'production_completed', label: '生产完成' }
];
const canCreate = computed(() => auth.hasPermission('supply.purchase_order.create'));
const canAccept = computed(() => auth.hasPermission('supply.purchase_order.accept'));
const canStart = computed(() => auth.hasPermission('supply.production.start'));
const canUpdate = computed(() => auth.hasPermission('supply.production.update'));
const canComplete = computed(() => auth.hasPermission('supply.production.complete'));

function statusLabel(status) {
  return Object.fromEntries(statusOptions.map((item) => [item.value, item.label]))[status] || status;
}

function statusType(status) {
  return {
    pending: 'warning',
    accepted: 'primary',
    in_production: '',
    production_completed: 'success'
  }[status] || 'info';
}

function progressPercent(order) {
  if (!Number(order.total_quantity)) return 0;
  return Math.min(100, Math.round((Number(order.completed_quantity) / Number(order.total_quantity)) * 100));
}

function statusCount(status) {
  return rows.value.filter((row) => row.status === status).length;
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-';
}

async function load() {
  state.value = 'loading';
  errorMessage.value = '';
  const response = await fetchSupplyOrders({
    ...filters,
    page: pagination.page,
    page_size: pagination.pageSize
  });
  if (!response.success) {
    state.value = 'error';
    errorMessage.value = response.message;
    return;
  }
  rows.value = response.data.results || response.data.items || [];
  total.value = response.data.count ?? rows.value.length;
  capability.value = response.data.api_status || 'connected';
  state.value = rows.value.length ? 'ready' : 'empty';
}

function applyFilters() {
  pagination.page = 1;
  load();
}

function resetFilters() {
  filters.search = '';
  filters.status = '';
  pagination.page = 1;
  load();
}

function changePage(page) {
  pagination.page = page;
  load();
}

function changePageSize(pageSize) {
  pagination.pageSize = pageSize;
  pagination.page = 1;
  load();
}

async function openDetail(row) {
  const response = await fetchSupplyOrder(row.id);
  if (!response.success) {
    ElMessage.error(response.message);
    return;
  }
  selected.value = response.data;
  capability.value = response.data.api_status || capability.value;
  detailOpen.value = true;
}

function openCreate() {
  createForm.order_no = `SC-LOCAL-${Date.now()}`;
  createOpen.value = true;
}

async function submitCreate() {
  if (!createForm.order_no || !createForm.order_date || !createForm.expected_delivery_date) {
    ElMessage.warning('请填写采购单号、采购日期和预计交期');
    return;
  }
  submitting.value = true;
  const response = await createSupplyOrder({
    order_no: createForm.order_no,
    supplier_id: Number(createForm.supplier_id),
    order_date: createForm.order_date,
    expected_delivery_date: createForm.expected_delivery_date,
    currency: createForm.currency,
    notes: createForm.notes,
    lines: [
      {
        line_no: 1,
        sku_id: Number(createForm.sku_id),
        quantity: Number(createForm.quantity),
        unit_price: createForm.unit_price,
        expected_delivery_date: createForm.expected_delivery_date
      }
    ]
  });
  submitting.value = false;
  if (!response.success) {
    ElMessage.error(response.message);
    return;
  }
  createOpen.value = false;
  ElMessage.success('供应链采购单已保存到本地环境');
  await load();
}

async function runAction(row, action, payload = {}) {
  try {
    await ElMessageBox.confirm(
      `确认对采购单 ${row.order_no} 执行“${statusLabelForAction(action)}”？`,
      '确认业务动作',
      { type: 'warning' }
    );
  } catch {
    return;
  }
  submitting.value = true;
  const response = await runSupplyOrderAction(row.id, action, payload);
  submitting.value = false;
  if (!response.success) {
    ElMessage.error(response.message);
    return;
  }
  ElMessage.success(response.data.replayed ? '重复请求已安全复用原结果' : '业务状态已更新');
  await load();
  if (detailOpen.value) await openDetail(row);
}

function statusLabelForAction(action) {
  return {
    accept: '接单',
    'start-production': '开始生产',
    'update-progress': '更新进度',
    'complete-production': '生产完成'
  }[action] || action;
}

function openProgress(row) {
  progressTarget.value = row;
  progressForm.completed_quantity = Number(row.completed_quantity || 0);
  progressForm.note = '';
  progressOpen.value = true;
}

async function submitProgress() {
  const target = progressTarget.value;
  progressOpen.value = false;
  await runAction(target, 'update-progress', {
    completed_quantity: Number(progressForm.completed_quantity),
    note: progressForm.note
  });
}

onMounted(load);
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.summary-grid article {
  display: grid;
  gap: 5px;
  padding: 16px;
  border: 1px solid #dce5ef;
  border-radius: 10px;
  background: #fff;
}
.summary-grid span, .summary-grid small { color: #64748b; }
.summary-grid strong { color: #173a63; font-size: 26px; }
.page-scope-note {
  margin: -8px 0 14px;
  color: #64748b;
  font-size: 13px;
}
.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.filter-bar .el-input { max-width: 280px; }
.filter-bar .el-select { width: 180px; }
.pagination {
  justify-content: flex-end;
  margin-top: 16px;
}
.drawer-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}
.drawer-heading h2 { margin: 4px 0 0; }
.drawer-heading small { color: #64748b; }
h3 { margin: 22px 0 10px; }
.dialog-form { margin-top: 14px; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}
.form-span { grid-column: 1 / -1; }
@media (max-width: 900px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .summary-grid, .form-grid { grid-template-columns: 1fr; }
  .filter-bar { flex-wrap: wrap; }
  .form-span { grid-column: auto; }
}
</style>
