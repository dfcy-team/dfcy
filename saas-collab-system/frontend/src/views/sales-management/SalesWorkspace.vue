<template>
  <section class="sales-workspace" :aria-busy="loading">
    <header class="sales-header">
      <div>
        <p class="sales-eyebrow">{{ contract.eyebrow }}</p>
        <h1>{{ contract.title }}</h1>
        <p>{{ contract.description }}</p>
      </div>
      <div class="sales-header__actions">
        <el-tag :type="sourceTagType" effect="plain">{{ sourceStatusLabel }}</el-tag>
        <el-button v-if="canExport && mode !== 'exports'" @click="openExportDialog">按当前筛选申请导出</el-button>
        <el-button v-if="mode === 'exports'" type="primary" @click="openExportDialog">新建导出</el-button>
      </div>
    </header>

    <el-alert
      title="只读分析：本模块不会执行平台改价、退款、库存调整或订单状态写回。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="freshness-rail" aria-label="数据新鲜度与来源">
      <div class="freshness-rail__lead">
        <span class="status-dot" :class="sourceStatus" />
        <div><small>数据新鲜度与来源</small><strong>{{ sourceStatusLabel }}</strong></div>
      </div>
      <dl>
        <div><dt>最近更新时间</dt><dd>{{ refreshedAt || '尚无成功数据' }}</dd></div>
        <div><dt>数据范围</dt><dd>当前租户 · 当前角色 · 授权门店</dd></div>
        <div><dt>币种口径</dt><dd>{{ definition.currency_basis || '按来源币种展示' }}</dd></div>
        <div><dt>质量评分</dt><dd>{{ quality.score ?? '--' }}<span v-if="quality.score !== undefined"> / 100</span></dd></div>
      </dl>
    </section>

    <el-form v-if="contract.filters.length" class="sales-filters" :model="query" label-position="top" @submit.prevent="loadData">
      <div class="filter-grid">
        <el-form-item v-for="filter in contract.filters" :key="filter.key" :label="filter.label">
          <el-date-picker
            v-if="filter.type === 'daterange'"
            v-model="query[filter.key]"
            type="daterange"
            unlink-panels
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
          />
          <el-select v-else-if="filter.type === 'select'" v-model="query[filter.key]" placeholder="全部" clearable>
            <el-option v-for="option in filter.options" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-input v-else v-model="query[filter.key]" :placeholder="filter.placeholder || `输入${filter.label}`" clearable />
        </el-form-item>
      </div>
      <div class="filter-actions">
        <el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </el-form>

    <el-alert v-if="pageState === 'error'" :title="errorMessage" type="error" show-icon :closable="false" />

    <div v-loading="pageState === 'loading'" class="sales-content">
      <section v-if="metrics.length" class="metric-grid" aria-label="核心销售指标">
        <article v-for="metric in metrics" :key="metric.code" class="metric-card">
          <div><span>{{ metric.label }}</span><small>{{ metric.definition || '当前筛选口径' }}</small></div>
          <strong>{{ metric.value ?? 'N/A' }} <em>{{ metric.unit }}</em></strong>
          <p :class="metric.change_direction">{{ metric.change || '数据口径可追溯' }}</p>
        </article>
      </section>

      <div v-if="mode === 'overview' && trend.length" class="overview-grid">
        <section class="sales-panel trend-panel">
          <div class="panel-heading"><div><h2>销售趋势</h2><p>净销售额变化，点击明细可继续核对来源。</p></div><span>最近 7 个数据点</span></div>
          <div class="trend-chart" role="img" aria-label="最近七天净销售趋势">
            <div v-for="point in trend" :key="point.label" class="trend-column">
              <strong>{{ point.value }}</strong>
              <div><i :style="{ height: trendHeight(point.value) }" /></div>
              <span>{{ point.label }}</span>
            </div>
          </div>
        </section>
        <section class="sales-panel anomaly-panel">
          <div class="panel-heading"><div><h2>需要关注</h2><p>同步、退款与映射异常。</p></div><el-tag type="warning" effect="plain">{{ anomalies.length }} 项</el-tag></div>
          <button v-for="issue in anomalies" :key="issue.id" type="button" class="anomaly-row" @click="goToQuality">
            <span :class="['severity-mark', issue.severity]" />
            <span><strong>{{ issue.issue_type }}</strong><small>{{ issue.store_id }} · {{ issue.message }}</small></span>
            <b>查看</b>
          </button>
          <el-empty v-if="!anomalies.length" description="当前未发现需要关注的异常" :image-size="54" />
        </section>
      </div>

      <section v-if="mode === 'data-quality'" class="sales-panel source-panel">
        <div class="panel-heading">
          <div><h2>同步来源</h2><p>仅展示授权引用和运行结果，不在销售管理内配置凭据。</p></div>
          <el-button text type="primary" @click="goToIntegrations">前往 API 数据接入</el-button>
        </div>
        <el-table :data="sources" stripe>
          <el-table-column prop="platform" label="平台" min-width="120" />
          <el-table-column prop="region" label="区域" width="90" />
          <el-table-column prop="store_id" label="门店" min-width="180" />
          <el-table-column prop="credential_mask" label="授权连接" min-width="150" />
          <el-table-column prop="run_status" label="最近运行" width="110">
            <template #default="{ row }"><el-tag :type="statusType(row.run_status)" effect="light">{{ statusLabel(row.run_status) }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="last_success_at" label="最近成功" min-width="180" />
          <el-table-column prop="error_summary" label="错误摘要" min-width="240" show-overflow-tooltip />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" :disabled="!canRerun || !['failed', 'partial'].includes(row.run_status)" @click="openRerunDialog(row)">申请重跑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="sales-panel table-panel">
        <div class="panel-heading">
          <div><h2>{{ contract.tableTitle }}</h2><p>{{ contract.tableNote }}</p></div>
          <el-tag effect="plain">{{ total }} 条</el-tag>
        </div>
        <el-table v-if="rows.length" :data="rows" stripe @row-click="selectRow">
          <el-table-column
            v-for="column in contract.columns"
            :key="column.prop"
            :prop="column.prop"
            :label="column.label"
            :min-width="column.width || 120"
            :align="column.numeric ? 'right' : 'left'"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <el-tag v-if="column.status" :type="statusType(row[column.prop])" effect="light">{{ statusLabel(row[column.prop]) }}</el-tag>
              <span v-else>{{ displayValue(row[column.prop]) }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="mode === 'orders'" label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" @click.stop="selectRow(row)">查看详情</el-button>
              <el-button text @click.stop="copyReference(row.order_reference)">复制</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-else-if="pageState === 'empty'" class="guided-empty">
          <el-empty :description="contract.emptyText" />
          <div><el-button @click="resetFilters">调整筛选</el-button><el-button type="primary" plain @click="goToIntegrations">检查数据接入</el-button></div>
        </div>
        <el-pagination
          v-if="total > pageSize"
          v-model:current-page="page"
          background
          layout="prev, pager, next, total"
          :page-size="pageSize"
          :total="total"
          @current-change="loadData"
        />
      </section>
    </div>

    <el-drawer v-model="detailOpen" size="520px" title="只读详情">
      <dl v-if="selectedRow" v-loading="detailLoading" class="detail-list">
        <div v-for="column in contract.columns" :key="column.prop"><dt>{{ column.label }}</dt><dd>{{ displayValue(selectedRow[column.prop]) }}</dd></div>
      </dl>
      <section v-if="selectedRow?.lines?.length" class="detail-lines">
        <h3>订单行</h3>
        <el-table :data="selectedRow.lines" size="small">
          <el-table-column prop="sku" label="SKU" min-width="130" />
          <el-table-column prop="product_name" label="商品" min-width="180" />
          <el-table-column prop="quantity" label="数量" width="80" align="right" />
          <el-table-column prop="unit_price" label="单价" width="110" align="right" />
        </el-table>
      </section>
      <el-alert title="敏感客户字段已脱敏；详情查看不会触发平台写操作。" type="info" :closable="false" />
    </el-drawer>

    <el-dialog v-model="exportDialogOpen" title="新建销售导出" width="520px">
      <el-form label-position="top">
        <el-form-item label="导出类型">
          <el-select v-model="exportForm.export_type">
            <el-option v-for="option in exportTypes" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </el-form-item>
        <el-alert title="任务将继承当前租户、角色、数据范围和筛选条件，默认生成脱敏文件。" type="info" :closable="false" />
      </el-form>
      <template #footer><el-button @click="exportDialogOpen = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="submitExport">创建任务</el-button></template>
    </el-dialog>

    <el-dialog v-model="rerunDialogOpen" title="申请手工重跑" width="520px">
      <p class="dialog-context">{{ activeSource?.platform }} · {{ activeSource?.store_id }}</p>
      <el-input v-model="rerunReason" type="textarea" :rows="3" placeholder="说明失败原因和重跑目的" />
      <template #footer><el-button @click="rerunDialogOpen = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="submitRerun">提交申请</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { createSalesExport, fetchSalesOrderDetail, fetchSalesPage, requestSalesSyncRerun } from '../../api/salesManagement';
import { formatApiError } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { salesPageContracts } from './pageContracts';

const props = defineProps({ mode: { type: String, required: true } });
const router = useRouter();
const auth = useAuthStore();
const UI_STATES = ['loading', 'empty', 'error', 'pending', 'stale', 'partial'];
const contract = computed(() => salesPageContracts[props.mode] || salesPageContracts.overview);
const query = reactive({});
const loading = ref(false);
const errorMessage = ref('');
const rows = ref([]);
const metrics = ref([]);
const trend = ref([]);
const anomalies = ref([]);
const sources = ref([]);
const quality = ref({});
const definition = ref({});
const sourceStatus = ref('pending');
const refreshedAt = ref('');
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const selectedRow = ref(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const exportDialogOpen = ref(false);
const rerunDialogOpen = ref(false);
const rerunReason = ref('');
const activeSource = ref(null);
const actionLoading = ref(false);
const exportForm = reactive({ export_type: 'orders' });
const exportTypes = [
  { label: '订单汇总', value: 'orders' }, { label: '订单行', value: 'order_lines' },
  { label: '退款退货', value: 'returns' }, { label: '门店销售', value: 'store_sales' },
  { label: 'SKU 销售', value: 'sku_sales' }
];

const permissions = computed(() => new Set(auth.currentUser?.permissions || []));
const canExport = computed(() => auth.currentUser?.is_superuser || permissions.value.has('sales_management.export'));
const canRerun = computed(() => auth.currentUser?.is_superuser || permissions.value.has('sales_management.sync.rerun'));
const pageState = computed(() => loading.value ? 'loading' : errorMessage.value ? 'error' : rows.value.length ? 'success' : 'empty');
const sourceStatusLabel = computed(() => ({
  pending: '等待首批数据', stale: '数据已过期', partial: '部分数据可用', ready: '数据已更新', mock: '模拟数据'
}[sourceStatus.value] || '状态待确认'));
const sourceTagType = computed(() => ({ ready: 'success', partial: 'warning', stale: 'warning', pending: 'info', mock: 'info' }[sourceStatus.value] || 'info'));
const maxTrend = computed(() => Math.max(...trend.value.map((point) => Number(point.value) || 0), 1));

function initializeFilters() {
  Object.keys(query).forEach((key) => delete query[key]);
  contract.value.filters.forEach((filter) => { query[filter.key] = filter.type === 'daterange' ? recentThirtyDays() : ''; });
  page.value = 1;
}

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function recentThirtyDays() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 29);
  return [formatDate(start), formatDate(end)];
}

function requestParams() {
  const params = { page: page.value, page_size: pageSize };
  Object.entries(query).forEach(([key, value]) => {
    if (key === 'date_range' && value?.length === 2) {
      params.date_from = value[0];
      params.date_to = value[1];
    } else if (value !== '' && value !== null && (!Array.isArray(value) || value.length)) {
      params[key] = value;
    }
  });
  return params;
}

function normalizeRows(items) {
  return (items || []).map((item) => ({
    ...item,
    filter_summary: item.filter_summary || summarizeObject(item.filters),
    scope_summary: item.scope_summary || summarizeScope(item.data_scope)
  }));
}

function summarizeObject(value) {
  if (!value || !Object.keys(value).length) return '当前全部筛选';
  return Object.entries(value).map(([key, item]) => `${key}: ${Array.isArray(item) ? item.join('、') : item}`).join(' · ');
}

function summarizeScope(value) {
  if (!Array.isArray(value) || !value.length) return '当前授权范围';
  return value.some((scope) => scope.scope_type === 'all') ? '全部授权数据' : `${value.length} 组数据范围`;
}

async function loadData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetchSalesPage(props.mode, requestParams());
    if (!response?.success) {
      errorMessage.value = formatApiError(response);
      rows.value = [];
      return;
    }
    const data = response.data || {};
    rows.value = normalizeRows(data.results || data.issues || []);
    total.value = Number(data.count ?? rows.value.length);
    metrics.value = data.metrics || [];
    trend.value = data.trend || [];
    anomalies.value = data.anomalies || [];
    sources.value = data.sources || [];
    quality.value = data.quality || {};
    definition.value = data.definition || {};
    sourceStatus.value = data.source_status || data.api_status || 'pending';
    refreshedAt.value = data.refreshed_at || data.quality?.refreshed_at || '';
    if (data.api_status === 'degraded') errorMessage.value = data.api_error || response.message;
  } catch (error) {
    errorMessage.value = formatApiError({ message: error?.message });
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function resetFilters() { initializeFilters(); loadData(); }
function trendHeight(value) { return `${Math.max(10, (Number(value || 0) / maxTrend.value) * 100)}%`; }
function displayValue(value) { return Array.isArray(value) ? value.join('、') : (value ?? '--'); }
function statusLabel(value) {
  return ({ pending: '待处理', processing: '处理中', completed: '已完成', success: '成功', partial: '部分成功', failed: '失败', open: '待处理', resolved: '已解决', high: '高', medium: '中', low: '低', healthy: '健康', warning: '需关注', none: '无', confirmed: '已确认', fulfilled: '已履约' }[value] || value || '--');
}
function statusType(value) {
  return ({ completed: 'success', success: 'success', resolved: 'success', healthy: 'success', failed: 'danger', high: 'danger', partial: 'warning', warning: 'warning', pending: 'warning', processing: 'info', medium: 'warning', low: 'info' }[value] || 'info');
}
async function selectRow(row) {
  selectedRow.value = row;
  detailOpen.value = true;
  if (props.mode !== 'orders') return;
  detailLoading.value = true;
  const response = await fetchSalesOrderDetail(row.id);
  detailLoading.value = false;
  if (!response?.success) return ElMessage.error(formatApiError(response));
  selectedRow.value = response.data;
}
async function copyReference(value) { await navigator.clipboard?.writeText(value || ''); ElMessage.success('已复制脱敏订单号'); }
function goToQuality() { router.push('/sales-management/data-quality'); }
function goToIntegrations() { router.push('/integrations/sync-runs'); }
function openExportDialog() { exportDialogOpen.value = true; }
function newKey(prefix) { return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

async function submitExport() {
  actionLoading.value = true;
  const filters = requestParams();
  delete filters.page;
  delete filters.page_size;
  const response = await createSalesExport({ export_type: exportForm.export_type, filters }, newKey('sales-export'));
  actionLoading.value = false;
  if (!response?.success) return ElMessage.error(formatApiError(response));
  exportDialogOpen.value = false;
  ElMessage.success('导出任务已创建，可在任务列表查看进度');
  if (props.mode === 'exports') loadData();
}

function openRerunDialog(source) {
  activeSource.value = source;
  rerunReason.value = '';
  rerunDialogOpen.value = true;
}

async function submitRerun() {
  if (!rerunReason.value.trim()) return ElMessage.warning('请填写重跑原因');
  actionLoading.value = true;
  const response = await requestSalesSyncRerun(
    { sync_source_id: activeSource.value.id, reason: rerunReason.value.trim() },
    newKey('sales-rerun')
  );
  actionLoading.value = false;
  if (!response?.success) return ElMessage.error(formatApiError(response));
  rerunDialogOpen.value = false;
  ElMessage.success('重跑申请已提交并记录审计');
}

watch(() => props.mode, () => { initializeFilters(); loadData(); }, { immediate: true });
void UI_STATES;
</script>

<style scoped>
.sales-workspace { display: grid; gap: 16px; color: #172033; }
.sales-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.sales-eyebrow { margin: 0 0 6px; color: #0f766e; font-size: 12px; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
.sales-header h1 { margin: 0; font-size: 26px; letter-spacing: -.02em; }
.sales-header p:not(.sales-eyebrow) { max-width: 720px; margin: 8px 0 0; color: #64748b; font-size: 14px; line-height: 1.6; }
.sales-header__actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.freshness-rail { display: grid; grid-template-columns: 220px 1fr; gap: 24px; padding: 15px 18px; border: 1px solid #cbdbe0; border-left: 4px solid #0f766e; border-radius: 8px; background: linear-gradient(110deg, #f2fbf9 0, #fff 45%); box-shadow: 0 3px 14px rgba(15, 118, 110, .06); }
.freshness-rail__lead { display: flex; align-items: center; gap: 12px; }
.freshness-rail__lead div { display: grid; gap: 3px; }
.freshness-rail small, .freshness-rail dt { color: #64748b; font-size: 11px; }
.freshness-rail strong { font-size: 15px; }
.status-dot { width: 11px; height: 11px; border: 3px solid #e2e8f0; border-radius: 50%; background: #64748b; box-shadow: 0 0 0 4px #f1f5f9; }
.status-dot.ready { background: #059669; box-shadow: 0 0 0 4px #d1fae5; }
.status-dot.partial, .status-dot.stale { background: #d97706; box-shadow: 0 0 0 4px #fef3c7; }
.freshness-rail dl { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; margin: 0; }
.freshness-rail dl div { min-width: 0; padding-left: 16px; border-left: 1px solid #e2e8f0; }
.freshness-rail dd { margin: 5px 0 0; overflow: hidden; color: #334155; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.sales-filters { padding: 14px 16px; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; }
.filter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 4px 12px; }
.filter-grid :deep(.el-form-item) { margin: 0 0 10px; }
.filter-grid :deep(.el-select), .filter-grid :deep(.el-date-editor) { width: 100%; }
.filter-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 2px; border-top: 1px solid #eef2f6; }
.sales-content { display: grid; gap: 16px; min-height: 240px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-card { min-width: 0; padding: 16px; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; box-shadow: 0 2px 8px rgba(15, 23, 42, .035); }
.metric-card > div { display: grid; gap: 5px; }
.metric-card span { color: #475569; font-size: 13px; font-weight: 650; }
.metric-card small { overflow: hidden; color: #94a3b8; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.metric-card > strong { display: block; margin-top: 16px; font-size: 25px; font-variant-numeric: tabular-nums; letter-spacing: -.03em; }
.metric-card em { color: #64748b; font-size: 11px; font-style: normal; font-weight: 500; letter-spacing: 0; }
.metric-card p { margin: 9px 0 0; color: #64748b; font-size: 11px; }
.metric-card p.up { color: #047857; } .metric-card p.down { color: #b45309; }
.overview-grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(320px, .8fr); gap: 16px; }
.sales-panel { padding: 17px; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.panel-heading h2 { margin: 0; font-size: 16px; }
.panel-heading p { margin: 5px 0 0; color: #7b8798; font-size: 12px; line-height: 1.5; }
.trend-chart { display: grid; grid-template-columns: repeat(7, minmax(44px, 1fr)); align-items: end; gap: 10px; min-height: 220px; }
.trend-column { display: grid; grid-template-rows: 22px 158px 20px; gap: 4px; min-width: 0; color: #64748b; font-size: 11px; text-align: center; }
.trend-column > strong { overflow: hidden; color: #334155; font-size: 11px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; }
.trend-column > div { position: relative; overflow: hidden; border-radius: 4px 4px 0 0; background: #eef5f4; }
.trend-column i { position: absolute; right: 0; bottom: 0; left: 0; border-radius: 4px 4px 0 0; background: linear-gradient(180deg, #14b8a6, #0f766e); }
.anomaly-panel { min-width: 0; }
.anomaly-row { display: grid; grid-template-columns: 8px 1fr auto; align-items: center; gap: 10px; width: 100%; padding: 12px 0; border: 0; border-bottom: 1px solid #eef2f6; background: none; color: inherit; text-align: left; cursor: pointer; }
.anomaly-row span:nth-child(2) { display: grid; min-width: 0; gap: 4px; }
.anomaly-row strong { font-size: 13px; } .anomaly-row small { overflow: hidden; color: #64748b; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.anomaly-row b { color: #0f766e; font-size: 11px; }
.severity-mark { width: 7px; height: 28px; border-radius: 5px; background: #94a3b8; }
.severity-mark.high { background: #dc2626; } .severity-mark.medium { background: #d97706; }
.guided-empty { display: grid; justify-items: center; padding-bottom: 24px; }
.table-panel :deep(.el-table__row) { cursor: pointer; }
.table-panel :deep(.el-pagination) { justify-content: flex-end; margin-top: 16px; }
.detail-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin: 0 0 18px; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 8px; background: #e2e8f0; }
.detail-list div { min-width: 0; padding: 12px; background: #fff; }
.detail-list dt { color: #64748b; font-size: 11px; } .detail-list dd { margin: 5px 0 0; overflow-wrap: anywhere; font-size: 13px; }
.detail-lines { margin-bottom: 18px; } .detail-lines h3 { margin: 0 0 10px; font-size: 14px; }
.dialog-context { margin: 0 0 12px; color: #475569; font-size: 13px; }
@media (max-width: 1180px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .freshness-rail dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 820px) { .sales-header { flex-direction: column; } .sales-header__actions { flex-wrap: wrap; } .freshness-rail, .overview-grid { grid-template-columns: 1fr; } .freshness-rail dl { grid-template-columns: 1fr 1fr; } .freshness-rail dl div { padding: 0; border: 0; } }
@media (max-width: 560px) { .metric-grid, .freshness-rail dl, .detail-list { grid-template-columns: 1fr; } .sales-header__actions { align-items: stretch; flex-direction: column; width: 100%; } .trend-chart { gap: 5px; } }
</style>
