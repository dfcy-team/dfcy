<template>
  <AppPage
    :eyebrow="eyebrow"
    :title="title"
    :subtitle="subtitle"
    :boundary-note="boundaryNote"
    :capability="capability"
  >
    <template #action>
      <el-button
        v-if="createHandler && createAccess.visible"
        type="primary"
        :disabled="createAccess.disabled"
        :title="createAccess.reason"
        @click="openCreate"
      >
        新建{{ entityLabel }}
      </el-button>
    </template>

    <section class="resource-summary" aria-label="数据摘要">
      <div class="summary-item">
        <span>当前结果</span>
        <strong>{{ total }}</strong>
      </div>
      <div class="summary-item">
        <span>启用</span>
        <strong>{{ activeCount }}</strong>
      </div>
      <div class="summary-item">
        <span>停用</span>
        <strong>{{ inactiveCount }}</strong>
      </div>
      <div class="summary-item summary-item--scope">
        <span>数据边界</span>
        <strong>当前 tenant</strong>
      </div>
    </section>

    <section class="resource-toolbar" aria-label="筛选条件">
      <el-input
        v-model="filters.search"
        clearable
        :placeholder="`搜索${entityLabel}名称或编码`"
        @keyup.enter="loadData"
      />
      <el-select v-model="filters.status" clearable placeholder="全部状态">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="inactive" />
      </el-select>
      <el-button type="primary" @click="loadData">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <AppState
      v-if="pageState !== 'ready'"
      :status="pageState"
      :title="stateTitle"
      :detail="stateDetail"
      @action="handleStateAction"
    />

    <section v-else class="resource-table" aria-label="档案列表">
      <el-table :data="rows" border table-layout="fixed" @row-click="openDetail">
        <el-table-column
          v-for="column in columns"
          :key="column.prop"
          :prop="column.prop"
          :label="column.label"
          :min-width="column.width || 130"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <el-tag v-if="column.type === 'status'" :type="statusType(row[column.prop])" effect="plain">
              {{ statusLabel(row[column.prop]) }}
            </el-tag>
            <span v-else-if="column.type === 'list'">{{ (row[column.prop] || []).join('、') || '-' }}</span>
            <span v-else>{{ formatValue(row[column.prop]) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" :width="operationWidth" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">查看</el-button>
            <el-button
              v-if="statusHandler && manageAccess.visible"
              link
              :type="rowStatus(row) === 'active' ? 'danger' : 'success'"
              :disabled="manageAccess.disabled"
              :title="manageAccess.reason"
              @click.stop="confirmStatus(row)"
            >
              {{ rowStatus(row) === 'active' ? '停用' : '启用' }}
            </el-button>
            <slot name="row-actions" :row="row" />
          </template>
        </el-table-column>
      </el-table>

      <footer class="resource-pagination">
        <span>共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          :page-size="filters.page_size"
          :total="total"
          layout="prev, pager, next"
          @current-change="loadData"
        />
      </footer>
    </section>

    <el-drawer v-model="detailOpen" :title="`${entityLabel}详情`" size="min(520px, 92vw)">
      <el-descriptions :column="1" border>
        <el-descriptions-item v-for="column in columns" :key="column.prop" :label="column.label">
          <span v-if="column.type === 'list'">{{ (selectedRow[column.prop] || []).join('、') || '-' }}</span>
          <span v-else>{{ formatValue(selectedRow[column.prop]) }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <p class="drawer-note">字段可见性与数据范围由后端 tenant、permission 和 data_scope 最终校验。</p>
    </el-drawer>

    <el-dialog v-model="createOpen" :title="`新建${entityLabel}`" width="min(560px, 94vw)" destroy-on-close>
      <el-alert
        title="仅保存当前租户的档案信息；凭据、Token、Cookie 和 Session 不在此表单采集。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="create-form" @submit.prevent="submitCreate">
        <el-form-item v-for="field in formFields" :key="field.key" :label="field.label" :required="field.required">
          <el-select v-if="field.type === 'select'" v-model="createForm[field.key]" :placeholder="field.placeholder || '请选择'">
            <el-option v-for="option in field.options || []" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-input
            v-else
            v-model="createForm[field.key]"
            :type="field.type === 'password' ? 'password' : 'text'"
            :show-password="field.type === 'password'"
            :autocomplete="field.type === 'password' ? 'new-password' : 'off'"
            :placeholder="field.placeholder || `请输入${field.label}`"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from './AppPage.vue';
import AppState from './AppState.vue';
import { useMock } from '../api/request';
import { useAuthStore } from '../stores/auth';
import { getActionAccess } from '../utils/actionAccess';
import { statusFromApiResponse } from '../utils/uiState';

const props = defineProps({
  eyebrow: { type: String, default: 'SYSTEM MANAGEMENT' },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  boundaryNote: { type: String, default: '' },
  entityLabel: { type: String, required: true },
  loader: { type: Function, required: true },
  columns: { type: Array, default: () => [] },
  formFields: { type: Array, default: () => [] },
  createHandler: { type: Function, default: null },
  statusHandler: { type: Function, default: null },
  createPermission: { type: String, default: '' },
  managePermission: { type: String, default: '' },
  operationWidth: { type: Number, default: 132 }
});

const auth = useAuthStore();
const rows = ref([]);
const total = ref(0);
const pageState = ref('loading');
const stateTitle = ref('');
const stateDetail = ref('');
const capability = ref(useMock ? 'mock' : 'pending');
const detailOpen = ref(false);
const createOpen = ref(false);
const selectedRow = ref({});
const createForm = reactive({});
const submitting = ref(false);
const filters = reactive({ search: '', status: '', page: 1, page_size: 20 });

const createAccess = computed(() => getActionAccess(auth, { permission: props.createPermission }));
const manageAccess = computed(() => getActionAccess(auth, { permission: props.managePermission }));
const activeCount = computed(() => rows.value.filter((row) => rowStatus(row) === 'active').length);
const inactiveCount = computed(() => rows.value.filter((row) => rowStatus(row) === 'inactive').length);

function rowStatus(row) {
  if (typeof row.is_active === 'boolean') return row.is_active ? 'active' : 'inactive';
  return row.status || 'unknown';
}

function statusType(value) {
  const normalized = typeof value === 'boolean' ? (value ? 'active' : 'inactive') : value;
  return { active: 'success', inactive: 'info', disabled: 'info', pending: 'warning' }[normalized] || 'info';
}

function statusLabel(value) {
  const normalized = typeof value === 'boolean' ? (value ? 'active' : 'inactive') : value;
  return { active: '启用', inactive: '停用', disabled: '禁用', pending: '待处理' }[normalized] || normalized || '-';
}

function formatValue(value) {
  if (value === true) return '是';
  if (value === false) return '否';
  if (Array.isArray(value)) return value.join('、') || '-';
  return value ?? '-';
}

function unpack(response) {
  const data = response?.data || {};
  const results = Array.isArray(data.results) ? data.results : (Array.isArray(data.items) ? data.items : []);
  return { data, results, count: Number.isFinite(data.count) ? data.count : results.length };
}

async function loadData() {
  pageState.value = 'loading';
  stateTitle.value = '';
  stateDetail.value = '';
  const response = await props.loader({ ...filters });
  if (!response?.success) {
    pageState.value = statusFromApiResponse(response, navigator.onLine);
    stateDetail.value = response?.message || '接口请求失败';
    capability.value = response?.http_status ? 'pending' : 'degraded';
    return;
  }
  const payload = unpack(response);
  rows.value = payload.results;
  total.value = payload.count;
  const apiStatus = payload.data.api_status || payload.data.status || (useMock ? 'mock' : 'pending');
  capability.value = apiStatus === 'fallback' ? 'degraded' : apiStatus;
  pageState.value = rows.value.length ? 'ready' : 'empty';
}

function resetFilters() {
  filters.search = '';
  filters.status = '';
  filters.page = 1;
  loadData();
}

function handleStateAction() {
  if (pageState.value === 'empty') resetFilters();
  else loadData();
}

function openDetail(row) {
  selectedRow.value = row;
  detailOpen.value = true;
}

function openCreate() {
  if (!createAccess.value.allowed) {
    ElMessage.warning(createAccess.value.reason);
    return;
  }
  for (const key of Object.keys(createForm)) delete createForm[key];
  for (const field of props.formFields) createForm[field.key] = field.default ?? '';
  createOpen.value = true;
}

async function submitCreate() {
  if (!createAccess.value.allowed || !props.createHandler) return;
  const missing = props.formFields.find((field) => field.required && !createForm[field.key]);
  if (missing) {
    ElMessage.warning(`请填写${missing.label}`);
    return;
  }
  submitting.value = true;
  try {
    const response = await props.createHandler({ ...createForm });
    if (!response?.success) throw new Error(response?.message || '保存失败');
    ElMessage.success(response.message || '保存成功');
    createOpen.value = false;
    await loadData();
  } catch (error) {
    ElMessage.error(error?.message || '保存失败');
  } finally {
    submitting.value = false;
  }
}

async function confirmStatus(row) {
  if (!manageAccess.value.allowed || !props.statusHandler) return;
  const next = rowStatus(row) === 'active' ? 'inactive' : 'active';
  try {
    await ElMessageBox.confirm(
      `确认将${props.entityLabel}“${row.name || row.username || row.code}”设为${statusLabel(next)}？`,
      '状态变更确认',
      { type: next === 'inactive' ? 'warning' : 'info' }
    );
    const response = await props.statusHandler(row, next);
    if (!response?.success) throw new Error(response?.message || '状态变更失败');
    ElMessage.success('状态已更新');
    await loadData();
  } catch (error) {
    if (error === 'cancel') return;
    ElMessage.error(error?.message || '状态变更失败');
  }
}

defineExpose({ loadData });
loadData();
</script>

<style scoped>
.resource-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(112px, 160px)) minmax(180px, 1fr);
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}

.summary-item { min-height: 74px; padding: 14px 16px; border-right: 1px solid #e5eaf0; }
.summary-item:last-child { border-right: 0; }
.summary-item span { display: block; color: #64748b; font-size: 12px; }
.summary-item strong { display: block; margin-top: 8px; color: #172033; font-size: 20px; }
.summary-item--scope strong { font-size: 15px; }

.resource-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 380px) 160px auto auto 1fr;
  gap: 10px;
  align-items: center;
  margin-top: 16px;
  padding: 12px;
  border: 1px solid #dbe3ec;
  background: #fff;
}

.resource-table { min-width: 0; margin-top: 16px; overflow: hidden; }
.resource-pagination { display: flex; align-items: center; justify-content: space-between; padding: 12px 2px 0; color: #64748b; font-size: 13px; }
.drawer-note { margin: 16px 0 0; color: #64748b; font-size: 12px; line-height: 1.6; }
.create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; margin-top: 16px; }

@media (max-width: 760px) {
  .resource-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item:nth-child(2) { border-right: 0; }
  .summary-item:nth-child(-n + 2) { border-bottom: 1px solid #e5eaf0; }
  .resource-toolbar { grid-template-columns: 1fr 1fr; }
  .resource-toolbar .el-input { grid-column: 1 / -1; }
  .create-form { grid-template-columns: 1fr; }
}
</style>
