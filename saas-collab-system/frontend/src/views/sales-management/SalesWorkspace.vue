<template>
  <section class="sales-workspace" :class="{ 'sales-overview': isReport, 'sales-order-report': mode === 'overview', 'sales-store-report': mode === 'stores', 'sales-sku-report': mode === 'skus' }" :aria-busy="loading">
    <header class="sales-header">
      <div>
        <p v-if="!isReport" class="sales-eyebrow">{{ contract.eyebrow }}</p>
        <h1>{{ contract.title }}</h1>
        <p>{{ contract.description }}</p>
      </div>
      <div class="sales-header__actions">
        <el-tag :type="sourceTagType" effect="plain">{{ sourceStatusLabel }}</el-tag>
        <el-button v-if="canExport" :disabled="isReport && (loading || !appliedOverviewFilters)" @click="openExportDialog">{{ isReport ? '按已查询条件申请导出' : '按当前筛选申请导出' }}</el-button>
      </div>
    </header>

    <el-alert
      v-if="!isReport"
      title="只读分析：本模块不会执行平台改价、退款、库存调整或订单状态写回。"
      type="info"
      show-icon
      :closable="false"
    />

    <section v-if="mode !== 'exports' && !isReport" class="freshness-rail" aria-label="数据新鲜度与来源">
      <div class="freshness-rail__lead">
        <span class="status-dot" :class="sourceStatus" />
        <div><small>数据新鲜度与来源</small><strong>{{ sourceStatusLabel }}</strong></div>
      </div>
      <dl>
        <div><dt>来源更新时间（UTC）</dt><dd>{{ refreshedAt ? formatField(refreshedAt, { format: 'datetime' }) : '尚无来源时间' }}</dd></div>
        <div><dt>数据范围</dt><dd>当前租户 · 当前角色 · 授权门店</dd></div>
        <div><dt>币种口径</dt><dd>按来源币种分别展示，不跨币种相加</dd></div>
        <div><dt>质量检查评分</dt><dd>{{ quality.checked_rows === 0 || quality.score == null ? '尚未评估' : `${quality.score} / 100` }}</dd></div>
      </dl>
    </section>

    <p v-if="quality.checked_rows > 0 && !isReport" class="field-note">质量检查覆盖 {{ formatField(quality.checked_rows, { numeric: true }) }} 条事实记录，发现 {{ formatField(quality.problem_rows, { numeric: true }) }} 条问题。评分不代表同步成功率或 SKU 关联率。</p>

    <div v-if="mode === 'skus'" class="overview-detail-switch" role="group" aria-label="SKU 汇总方式"><el-button :type="skuGrouping === 'store' ? 'primary' : 'default'" :aria-pressed="skuGrouping === 'store'" @click="changeSkuGrouping('store')">按店铺 SKU 汇总</el-button><el-button :type="skuGrouping === 'product' ? 'primary' : 'default'" :aria-pressed="skuGrouping === 'product'" @click="changeSkuGrouping('product')">按商品 SKU 汇总</el-button></div>
    <el-form v-if="resolvedFilters.length" class="sales-filters" :class="{ 'order-filters': mode === 'orders' }" :model="query" label-position="top" @submit.prevent="applyFilters">
      <div class="filter-grid">
        <el-form-item v-for="filter in resolvedFilters" :key="filter.key" :label="filter.label" :class="`filter-${filter.key}`">
          <div v-if="isReport && filter.type === 'daterange'" class="quick-dates" role="group" aria-label="快捷日期"><button v-for="days in [1, 7, 15, 30]" :key="days" type="button" :aria-pressed="isQuickRange(days)" @click="applyQuickRange(days)">{{ days === 1 ? '昨天' : `过去${days}天` }}</button></div>
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
          <el-select
            v-else-if="filter.type === 'select'"
            v-model="query[filter.key]"
            placeholder="全部"
            :multiple="isMultiFilter(filter.key)"
            collapse-tags
            collapse-tags-tooltip
            clearable
            @change="filter.key === 'platform' && onPlatformChange()"
          >
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

    <p v-if="hasUnappliedFilters" class="field-note">筛选已修改，请点击查询。当前报表与导出仍使用上次查询条件。</p>

    <el-alert v-if="pageState === 'error'" :title="errorMessage" type="error" show-icon :closable="false" />

    <div v-loading="pageState === 'loading'" class="sales-content">
      <SalesReportTable v-if="mode === 'overview'" title="订单概览 · 最近两个有数据日期" :rows="recentOrderDays" />
      <template v-if="isReport"><SalesOverviewPanel v-for="(code, index) in reportCurrencies" :key="code" :currency-code="code" :data="overviewData" :store-report="mode === 'stores'" :report-kind="mode">
        <template v-if="mode === 'overview' && index === 0" #date-controls>
          <div class="summary-dates" role="group" aria-label="汇总数据日期筛选">
            <div class="quick-dates"><button v-for="days in [1, 7, 15, 30]" :key="days" type="button" :aria-pressed="isQuickRange(days)" @click="applyQuickRange(days)">{{ days === 1 ? '昨天' : `过去${days}天` }}</button></div>
            <el-date-picker v-model="query.date_range" type="daterange" unlink-panels range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" aria-label="汇总数据日期范围" @change="applyFilters" />
          </div>
        </template>
      </SalesOverviewPanel></template>
      <SalesReportTable v-if="mode === 'overview'" title="订单汇总明细" :rows="overviewData.order_daily || []" />
      <template v-if="mode === 'skus'"><SalesReportTable title="产品销量信息" :sku-report="true" :rows="rows" @sort="sortSkus" /><el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next, total" background @current-change="loadData(true)" /></template>
      <section v-if="metrics.length && !isReport" class="metric-grid" aria-label="核心销售指标">
        <article v-for="metric in metrics" :key="metric.code" class="metric-card">
          <div><span>{{ metric.label }}</span><small>{{ metric.definition || '当前筛选口径' }}</small></div>
          <strong>{{ metric.display }} <em>{{ metric.unit }}</em></strong>
          <p>{{ metric.change || '当前筛选范围 · 无同期对比' }}</p>
        </article>
      </section>

      <details v-if="isReport" class="overview-source">
        <summary>数据来源与质量 · {{ refreshedAt ? formatField(refreshedAt, { format: 'datetime' }) + ' UTC' : '尚无来源时间' }}</summary>
        <p>当前租户 · 当前角色 · 授权门店。质量检查评分：{{ quality.checked_rows === 0 || quality.score == null ? '尚未评估' : `${quality.score} / 100` }}。评分不代表同步成功率或 SKU 关联率。</p>
        <p>只读分析，不执行平台改价、退款或订单状态写回。</p>
        <p>{{ Array.isArray(overviewData.anomalies) ? `接口返回 ${overviewData.anomalies.length} 条异常记录` : `${mode === 'stores' ? '门店报告' : '总览'}接口未提供异常明细，请到数据同步与质量核查。` }}</p>
        <p v-for="issue in overviewData.anomalies || []" :key="issue.id">{{ issue.issue_type }} · {{ issue.message }} <el-button text type="primary" @click="goToIntegrations">查看同步</el-button></p>
        <el-button text type="primary" @click="router.push('/sales-management/data-quality')">查看数据同步与质量</el-button>
      </details>

      <section v-if="mode === 'data-quality'" class="sales-panel table-panel">
        <div class="panel-heading"><div><h2>同步来源</h2><p>展示接口返回的授权范围内任务，最多 100 条；查看本页不会启动同步。</p></div></div>
        <el-table :data="sources" stripe empty-text="尚无可见同步来源，或当前角色没有同步查看权限。">
          <el-table-column v-for="column in sourceColumns" :key="column.prop" :label="column.label" :min-width="column.width || 140" :align="column.numeric ? 'right' : 'left'" show-overflow-tooltip>
            <template #default="{ row }"><el-tag v-if="column.status" :type="statusType(valueAt(row, column.prop))">{{ formatField(valueAt(row, column.prop), column) }}</el-tag><span v-else>{{ formatField(valueAt(row, column.prop), column) }}</span></template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="!['overview', 'skus'].includes(mode)" class="sales-panel table-panel">
        <div class="panel-heading">
          <div><h2>{{ contract.tableTitle }}</h2><p>{{ contract.tableNote }}</p></div>
          <el-tag effect="plain">{{ total }} 条</el-tag>
          <details v-if="mode === 'stores'" class="store-columns"><summary>展示列</summary><div><label v-for="column in contract.columns" :key="column.prop"><input v-model="storeColumns" type="checkbox" :value="column.prop" :disabled="column.prop === 'store_name'">{{ column.label }}</label></div></details>
        </div>
        <p class="field-note">金额保留两位小数，数量使用千分位；“—”表示未提供，不等于 0。时间统一为 UTC。点击详情可核对完整字段和原始值。</p>
        <el-table v-if="rows.length || pageState === 'empty'" :data="rows" :empty-text="contract.emptyText" stripe @row-click="selectRow" @sort-change="sortStores">
          <el-table-column
            v-for="column in displayedColumns"
            :key="column.prop"
            :prop="column.prop"
            :label="column.label"
            :min-width="column.width || 120"
            :align="column.numeric ? 'right' : 'left'"
            :sortable="mode === 'stores' ? 'custom' : false"
            :fixed="mode === 'stores' && column.prop === 'store_name' ? 'left' : false"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <el-tag v-if="column.status" :type="statusType(valueAt(row, column.prop))" effect="light">{{ statusLabel(valueAt(row, column.prop)) }}</el-tag>
              <div v-else-if="mode === 'stores' && column.prop === 'store_name'" class="store-identity"><strong>{{ row.store_name || row.store_code }}</strong><small>{{ formatField(row.platform, { format: 'platform' }) }} · {{ row.region || '站点未提供' }}</small></div>
              <span v-else :class="{ 'numeric-value': column.numeric }">{{ formatField(valueAt(row, column.prop) ?? valueAt(row, column.fallback), column) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="mode === 'orders' ? 150 : 100" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" @click.stop="selectRow(row)">查看详情</el-button>
              <el-button v-if="mode === 'orders'" text @click.stop="copyReference(row.external_order_id)">复制</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="pageState === 'empty'" class="guided-empty">
          <div><el-button @click="resetFilters">调整筛选</el-button><el-button v-if="mode !== 'exports'" type="primary" plain @click="goToIntegrations">检查数据接入</el-button></div>
        </div>
        <el-pagination
          v-if="total > pageSize"
          v-model:current-page="page"
          background
          layout="prev, pager, next, total"
          :page-size="pageSize"
          :total="total"
          @current-change="loadData(isReport)"
        />
      </section>
    </div>

    <el-drawer v-model="detailOpen" size="min(960px, 100vw)" :title="`${contract.title} · 只读详情`" @closed="closeDetail">
      <dl v-if="selectedRow" v-loading="detailLoading" class="detail-list">
        <div v-for="column in contract.columns" :key="column.prop"><dt>{{ column.label }}</dt><dd>{{ formatField(valueAt(selectedRow, column.prop), column) }}<small v-if="column.format === 'money' && valueAt(selectedRow, column.prop) != null" class="raw-value">原始金额：{{ valueAt(selectedRow, column.prop) }}</small></dd></div>
      </dl>
      <section v-if="selectedRow?.items?.length" class="detail-lines">
        <h3>商品行</h3>
        <el-table :data="selectedRow.items" size="small">
          <el-table-column prop="seller_sku" label="平台 SKU" min-width="160" />
          <el-table-column label="内部 SKU" min-width="160"><template #default="{ row }">{{ row.internal_sku || '未关联' }}</template></el-table-column>
          <el-table-column prop="item_name_snapshot" label="商品" min-width="180" />
          <el-table-column prop="currency" label="币种" width="80" />
          <el-table-column v-for="column in itemColumns" :key="column.prop" :label="column.label" min-width="120" align="right"><template #default="{ row }"><span :title="String(valueAt(row, column.prop) ?? '')">{{ formatField(valueAt(row, column.prop), column) }}</span></template></el-table-column>
        </el-table>
      </section>
      <section v-if="selectedRow?.refund_returns?.length" class="detail-lines">
        <h3>退款退货</h3>
        <article v-for="refund in selectedRow.refund_returns" :key="refund.id" class="refund-card">
          <dl class="detail-list">
            <div><dt>售后单号</dt><dd>{{ displayValue(refund.external_return_id) }}</dd></div>
            <div><dt>退款单号</dt><dd>{{ displayValue(refund.external_refund_id) }}</dd></div>
            <div><dt>类型 / 状态</dt><dd>{{ statusLabel(refund.case_type) }} / {{ statusLabel(refund.normalized_status) }}</dd></div>
            <div><dt>退款金额</dt><dd>{{ refund.currency }} {{ formatField(refund.refund_amount, { format: 'money' }) }}</dd></div>
            <div><dt>费用拆分（{{ refund.currency || '币种未提供' }}）</dt><dd>商品 {{ formatField(refund.refund_subtotal, { format: 'money' }) }} · 运费 {{ formatField(refund.refund_shipping_fee, { format: 'money' }) }} · 税 {{ formatField(refund.refund_tax, { format: 'money' }) }}</dd></div>
            <div><dt>退款标志</dt><dd>部分数量 {{ yesNo(refund.is_partial_quantity_return) }} · 金额调整 {{ yesNo(refund.is_refund_amount_adjusted) }}</dd></div>
          </dl>
          <el-table v-if="refund.items?.length" :data="refund.items" size="small">
            <el-table-column prop="seller_sku" label="平台 SKU" min-width="160" />
            <el-table-column prop="item_name_snapshot" label="商品" min-width="180" />
            <el-table-column prop="quantity" label="退款数量" width="100" align="right" />
            <el-table-column prop="currency" label="币种" width="80" />
            <el-table-column label="退款金额" width="120" align="right"><template #default="{ row }">{{ formatField(row.refund_amount, { format: 'money' }) }}</template></el-table-column>
          </el-table>
        </article>
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
        <p v-if="isReport" class="field-note">当前导出提供筛选范围内的销售事实明细，不是本页按日／SKU 聚合表。</p>
      </el-form>
      <template #footer><el-button @click="exportDialogOpen = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="submitExport">创建任务</el-button></template>
    </el-dialog>

  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { createSalesExport, fetchSalesFilters, fetchSalesOrderDetail, fetchSalesPage } from '../../api/salesManagement';
import { formatApiError } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { salesPageContracts } from './pageContracts';
import { formatField, formatMetric, statusLabel, statusType } from './display';
import SalesOverviewPanel from './SalesOverviewPanel.vue';
import SalesReportTable from './SalesReportTable.vue';
import { completedDateRange } from './overviewTrend';

const props = defineProps({ mode: { type: String, required: true } });
const router = useRouter();
const auth = useAuthStore();
const UI_STATES = ['loading', 'empty', 'error', 'pending', 'stale', 'partial'];
const contract = computed(() => salesPageContracts[props.mode] || salesPageContracts.overview);
const isReport = computed(() => ['overview', 'stores', 'skus'].includes(props.mode));
const skuGrouping = ref('store'), skuOrdering = ref('-gross_sales');
const recentOrderDays = computed(() => {
  const rows = overviewData.value.order_daily || [];
  const dates = [...new Set(rows.map(row => row.date))].sort().reverse().slice(0, 2);
  return rows.filter(row => dates.includes(row.date));
});
const storeColumns = ref(['store_name', 'gross_sales', 'currency', 'valid_order_count', 'order_count', 'units_sold', 'refund_amount', 'refund_case_count', 'cancelled_order_count', 'cancelled_amount', 'net_sales']);
const displayedColumns = computed(() => props.mode === 'stores' ? storeColumns.value.map(prop => contract.value.columns.find(column => column.prop === prop)).filter(Boolean) : contract.value.columns);
const storeOrdering = ref('');
const query = reactive({});
const filterData = reactive({ platforms: [], stores: [], currencies: [], order_statuses: [], refund_statuses: [] });
const resolvedFilters = computed(() => (isReport.value
  ? [...contract.value.filters].sort((a, b) => ['platform', 'store_id', 'currency', 'date_range', 'sku'].indexOf(a.key) - ['platform', 'store_id', 'currency', 'date_range', 'sku'].indexOf(b.key))
  : contract.value.filters).filter(filter => props.mode !== 'overview' || filter.key !== 'date_range').map((filter) => ({
  ...filter,
  options: filter.options || optionsFor(filter.optionSource)
})));
const loading = ref(false);
const errorMessage = ref('');
const rows = ref([]);
const metrics = ref([]);
const overviewData = ref({});
const reportCurrencies = computed(() => {
  const codes = [...new Set([overviewData.value.currency,
    ...(overviewData.value.currency_groups || []).map(group => group.currency),
    ...(overviewData.value.trend || []).flatMap(row => ['gross_sales', 'net_sales', 'refund_amount'].flatMap(field => Object.keys(row[field] || {})))
  ].filter(Boolean))].sort();
  return codes.length ? codes : [''];
});
const appliedOverviewFilters = ref(null);
const hasUnappliedFilters = computed(() => {
  if (!isReport.value || !appliedOverviewFilters.value) return false;
  const current = requestParams(), applied = appliedOverviewFilters.value;
  return [...new Set([...Object.keys(current), ...Object.keys(applied)])]
    .filter(key => !['page', 'page_size', 'ordering'].includes(key))
    .some(key => current[key] !== applied[key]);
});
const sources = ref([]);
const sourceColumns = [
  { prop: 'id', label: '任务编号', width: 100 }, { prop: 'platform', label: '平台', format: 'platform' },
  { prop: 'store_id', label: '来源标识', width: 220 }, { prop: 'resource', label: '同步内容', format: 'enum' },
  { prop: 'run_status', label: '最近运行状态', status: true },
  { prop: 'last_success_at', label: '最近成功（UTC）', format: 'datetime', width: 195 },
  { prop: 'last_run_at', label: '最近运行（UTC）', format: 'datetime', width: 195 },
  { prop: 'fetched_count', label: '最近获取记录数', numeric: true }, { prop: 'error_summary', label: '错误摘要', width: 240 }
];
const itemColumns = computed(() => props.mode === 'returns' ? [
  { prop: 'quantity', label: '退款数量', numeric: true }, { prop: 'refund_amount', label: '退款金额', format: 'money' }
] : [
  { prop: 'quantity', label: '数量', numeric: true },
  ...[['original_unit_price', '原价'], ['sale_unit_price', '折后单价'], ['discount_amount', '折扣金额'], ['line_total_amount', '商品行金额']].map(([prop, label]) => ({ prop, label, format: 'money' }))
]);
const quality = ref({});
const sourceStatus = ref('pending');
const refreshedAt = ref('');
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const selectedRow = ref(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const exportDialogOpen = ref(false);
const actionLoading = ref(false);
const exportForm = reactive({ export_type: 'orders' });
const exportTypes = [
  { label: '订单汇总', value: 'orders' }, { label: '订单行', value: 'order_lines' },
  { label: '退款退货', value: 'returns' }, { label: '门店销售', value: 'store_sales' },
  { label: 'SKU 销售', value: 'sku_sales' }
];

const permissions = computed(() => new Set(auth.currentUser?.permissions || []));
const canExport = computed(() => auth.currentUser?.is_superuser || permissions.value.has('sales_management.export'));
const pageState = computed(() => loading.value ? 'loading' : errorMessage.value ? 'error' : rows.value.length ? 'success' : 'empty');
const sourceStatusLabel = computed(() => errorMessage.value ? '读取失败' : loading.value ? '正在读取' : props.mode === 'exports' && sourceStatus.value !== 'mock' ? '任务列表已读取' : ({
  pending: '等待首批数据', stale: '数据已过期', partial: '部分数据可用', ready: '数据已更新', mock: '模拟数据'
}[sourceStatus.value] || '状态待确认'));
const sourceTagType = computed(() => errorMessage.value ? 'danger' : ({ ready: 'success', partial: 'warning', stale: 'warning', pending: 'info', mock: 'info' }[sourceStatus.value] || 'info'));
let requestSequence = 0;
let detailSequence = 0;

function optionsFor(source) {
  if (!source) return [];
  const values = filterData[source] || [];
  if (source === 'stores') {
    return values
      .filter((store) => Array.isArray(query.platform) ? !query.platform.length || query.platform.includes(store.platform) : !query.platform || store.platform === query.platform)
      .map((store) => ({ label: `${store.name} · ${store.region}`, value: store.id }));
  }
  const labels = { shopee: 'Shopee', tiktok: 'TikTok Shop' };
  return values.map((value) => ({ label: labels[value] || statusLabel(value), value }));
}

async function loadFilterOptions() {
  const response = await fetchSalesFilters(!isReport.value && query.platform ? { platform: query.platform } : {});
  if (!response?.success) return;
  Object.keys(filterData).forEach((key) => { filterData[key] = response.data?.[key] || []; });
}

function isMultiFilter(key) { return isReport.value && ['platform', 'store_id'].includes(key); }

function initializeFilters() {
  Object.keys(query).forEach((key) => delete query[key]);
  contract.value.filters.forEach((filter) => { query[filter.key] = filter.type === 'daterange' ? (isReport.value ? completedDateRange(30) : recentThirtyDays()) : isMultiFilter(filter.key) ? [] : ''; });
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
  if (props.mode === 'skus') Object.assign(params, { report: 'true', grouping: skuGrouping.value, ordering: skuOrdering.value });
  if (props.mode === 'stores' && storeOrdering.value) params.ordering = storeOrdering.value;
  Object.entries(query).forEach(([key, value]) => {
    if (key === 'date_range' && value?.length === 2) {
      params.date_from = value[0];
      params.date_to = value[1];
    } else if (value !== '' && value !== null && (!Array.isArray(value) || value.length)) {
      if (isMultiFilter(key) && Array.isArray(value)) {
        params[key === 'platform' ? 'platforms' : 'store_ids'] = [...value].sort().join(',');
      } else params[key] = value;
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

async function loadData(useApplied = false) {
  const sequence = ++requestSequence;
  const params = isReport.value && useApplied === true && appliedOverviewFilters.value
    ? { ...appliedOverviewFilters.value, page: page.value, page_size: pageSize }
    : requestParams();
  if (props.mode === 'stores') {
    delete params.ordering;
    if (storeOrdering.value) params.ordering = storeOrdering.value;
  }
  if (props.mode === 'skus') params.ordering = skuOrdering.value;
  appliedOverviewFilters.value = null;
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetchSalesPage(props.mode, params);
    if (sequence !== requestSequence) return;
    if (!response?.success) {
      errorMessage.value = formatApiError(response);
      clearData();
      return;
    }
    const data = response.data || {};
    rows.value = normalizeRows(data.results || data.issues || []);
    total.value = Number(data.count ?? rows.value.length);
    metrics.value = data.metrics?.length
      ? data.metrics.map(formatMetric)
      : (data.currency_groups || []).flatMap((group) =>
          (group.metrics || []).map((metric) => { const formatted = formatMetric(metric); return { ...formatted, code: `${group.currency}-${metric.code}`, label: `${group.currency} · ${formatted.label}` }; })
        );
    overviewData.value = isReport.value ? data : {};
    if (isReport.value) {
      const { page: ignoredPage, page_size: ignoredSize, ...filters } = params;
      appliedOverviewFilters.value = filters;
    }
    sources.value = data.sources || [];
    quality.value = data.quality || {};
    sourceStatus.value = data.api_status === 'mock' ? 'mock' : data.source_status || 'pending';
    refreshedAt.value = data.refreshed_at || data.quality?.refreshed_at || '';
    if (data.api_status === 'degraded') errorMessage.value = data.api_error || response.message;
  } catch (error) {
    if (sequence !== requestSequence) return;
    errorMessage.value = formatApiError({ message: error?.message });
    clearData();
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function applyFilters() { page.value = 1; selectedRow.value = null; loadData(); }
function changeSkuGrouping(grouping) { skuGrouping.value = grouping; page.value = 1; loadData(); }
function sortSkus({ prop, order }) { skuOrdering.value = order ? `${order === 'descending' ? '-' : ''}${prop}` : '-gross_sales'; page.value = 1; loadData(true); }
function sortStores({ prop, order }) {
  if (props.mode !== 'stores') return;
  storeOrdering.value = order ? `${order === 'descending' ? '-' : ''}${prop}` : '';
  page.value = 1;
  selectedRow.value = null;
  loadData(true);
}
function isQuickRange(days) { return JSON.stringify(query.date_range) === JSON.stringify(completedDateRange(days)); }
function applyQuickRange(days) { query.date_range = completedDateRange(days); applyFilters(); }
function resetFilters() { initializeFilters(); loadFilterOptions(); loadData(); }
function onPlatformChange() {
  if (isReport.value) {
    const allowed = new Set(optionsFor('stores').map(store => store.value));
    query.store_id = (Array.isArray(query.store_id) ? query.store_id : []).filter(id => allowed.has(id));
  } else query.store_id = '';
  page.value = 1;
  selectedRow.value = null;
  detailOpen.value = false;
  if (!isReport.value) loadFilterOptions();
  if (!isReport.value) loadData();
}
function clearData() {
  rows.value = []; metrics.value = []; overviewData.value = {}; sources.value = [];
  appliedOverviewFilters.value = null;
  total.value = 0; quality.value = {}; refreshedAt.value = ''; sourceStatus.value = 'pending';
}
function displayValue(value) { return formatField(value); }
function valueAt(row, path) { return path?.split('.').reduce((value, key) => value?.[key], row); }
function yesNo(value) { return value === null || value === undefined ? '—' : (value ? '是' : '否'); }
async function selectRow(row) {
  const sequence = ++detailSequence;
  selectedRow.value = row;
  detailOpen.value = true;
  if (props.mode !== 'orders') return;
  detailLoading.value = true;
  try {
    const response = await fetchSalesOrderDetail(row.id);
    if (sequence !== detailSequence) return;
    if (!response?.success) return ElMessage.error(formatApiError(response));
    selectedRow.value = response.data;
  } catch (error) {
    if (sequence === detailSequence) ElMessage.error(formatApiError({ message: error?.message }));
  } finally { if (sequence === detailSequence) detailLoading.value = false; }
}
function closeDetail() { ++detailSequence; detailLoading.value = false; selectedRow.value = null; }
async function copyReference(value) { await navigator.clipboard?.writeText(value || ''); ElMessage.success('已复制平台订单号'); }
function goToIntegrations() { router.push('/integrations/sync-runs'); }
function openExportDialog() { if (isReport.value && (loading.value || !appliedOverviewFilters.value)) return; if (props.mode === 'stores') exportForm.export_type = 'store_sales'; exportDialogOpen.value = true; }
function newKey(prefix) { return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

async function submitExport() {
  if (isReport.value && (loading.value || !appliedOverviewFilters.value)) return;
  actionLoading.value = true;
  const filters = isReport.value ? { ...appliedOverviewFilters.value } : requestParams();
  for (const key of ['platforms', 'store_ids']) {
    if (filters[key]) filters[key] = filters[key].split(',').map(value => key === 'store_ids' ? Number(value) : value);
  }
  delete filters.page;
  delete filters.page_size;
  delete filters.ordering;
  delete filters.report;
  delete filters.grouping;
  const response = await createSalesExport({ export_type: exportForm.export_type, filters }, newKey('sales-export'));
  actionLoading.value = false;
  if (!response?.success) return ElMessage.error(formatApiError(response));
  exportDialogOpen.value = false;
  ElMessage.success('导出任务已创建，可在任务列表查看进度');
}

watch(() => props.mode, () => { ++detailSequence; detailOpen.value = false; detailLoading.value = false; selectedRow.value = null; clearData(); initializeFilters(); loadFilterOptions(); loadData(); }, { immediate: true });
void UI_STATES;
</script>

<style scoped>
.sales-workspace { display: grid; gap: 16px; color: #172033; }
.sales-overview { gap: 12px; container: sales-overview / inline-size; min-width: 0; }
.sales-store-report .panel-heading { flex-wrap: wrap; }
.store-columns { font-size: 13px; color: #475569; }
.store-columns summary { cursor: pointer; padding: 6px 0; }
.store-columns[open] { flex-basis: 100%; }
.store-columns > div { display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 10px 0; }
.store-columns label { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; }
.store-columns input { accent-color: #5941c6; }
.store-identity { display: grid; gap: 4px; }
.store-identity strong { font-weight: 500; }
.store-identity small { color: #596579; font-size: 12px; }
.sales-overview .sales-header { align-items: center; }
.sales-overview .sales-header h1 { font-size: 22px; }
.sales-overview .sales-header p { margin-top: 4px; font-size: 12px; }
.sales-overview .sales-filters { display: grid; grid-template-columns: 140px minmax(160px, 200px) 110px minmax(0, 1fr) auto; align-items: end; gap: 12px; padding: 12px 14px; border-radius: 6px; }
.sales-overview .filter-grid { display: contents; }
.sales-order-report .sales-filters { display: flex; flex-wrap: wrap; }
.sales-order-report .filter-grid :deep(.el-form-item) { flex: 0 1 200px; }
.sales-order-report .sales-filters .filter-actions { margin-left: auto; }
.summary-dates { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; }
.summary-dates :deep(.el-date-editor) { width: 280px; max-width: 100%; flex: 0 1 280px; }
@media (max-width: 600px) {
  .summary-dates { width: 100%; }
  .summary-dates :deep(.el-date-editor) { flex: 1 1 100%; width: 100%; min-width: 0; }
  .sales-order-report .filter-grid :deep(.el-form-item) { flex: 1 1 100%; }
}
.sales-overview .filter-grid :deep(.el-form-item) { min-width: 0; margin: 0; }
.sales-overview .filter-grid :deep(.el-form-item.filter-date_range) { grid-column: 4; }
.sales-overview .filter-grid :deep(.el-form-item.filter-sku) { grid-column: 1 / 3; grid-row: 2; }
.sales-overview :deep(.filter-date_range .el-form-item__content) { display: flex; flex-wrap: nowrap; gap: 8px; }
.sales-overview :deep(.filter-date_range .el-date-editor) { flex: 1; width: 100%; min-width: 280px; height: 32px; }
.sales-overview .filter-grid :deep(.el-form-item__label) { margin-bottom: 5px; font-size: 12px; color: #475569; }
.sales-overview .filter-actions { border: 0; padding: 0; }
.sales-overview .filter-actions :deep(.el-button + .el-button) { margin-left: 0; }
.sales-overview .filter-actions :deep(.el-button--primary) { --el-button-bg-color: #5941c6; --el-button-border-color: #5941c6; --el-button-hover-bg-color: #4933aa; --el-button-hover-border-color: #4933aa; }
.overview-source { padding: 10px 14px; color: #475569; font-size: 12px; line-height: 1.7; }
.overview-source summary { cursor: pointer; width: fit-content; }
.overview-source p { margin: 8px 0; }
.quick-dates { display: inline-flex; flex: 0 0 auto; }
.quick-dates button { height: 32px; padding: 0 10px; border: 1px solid #dce3ec; background: #fff; color: #334155; cursor: pointer; font: inherit; font-size: 12px; white-space: nowrap; line-height: 1; }
.quick-dates button + button { margin-left: -1px; }
.quick-dates button:first-child { border-radius: 4px 0 0 4px; }
.quick-dates button:last-child { border-radius: 0 4px 4px 0; }
.quick-dates button:hover { background: #f4f1ff; }
.quick-dates button[aria-pressed=true] { color: #513ab9; border-color: #6952d9; background: #f4f1ff; }
.quick-dates button:focus-visible { outline: 2px solid #6952d9; outline-offset: 2px; }
.overview-detail-switch { display: flex; gap: 8px; flex-wrap: wrap; padding-top: 8px; }
@container sales-overview (max-width: 1250px) {
  .sales-sku-report .filter-grid :deep(.el-form-item.filter-date_range) { grid-row: 2; }
  .sales-sku-report .filter-grid :deep(.el-form-item.filter-sku) { grid-row: 3; }
  .sales-sku-report .sales-filters .filter-actions { grid-row: 3; }
  .sales-overview .sales-filters { grid-template-columns: minmax(120px, 1fr) minmax(160px, 1.4fr) minmax(100px, .8fr); }
  .sales-overview .filter-grid :deep(.el-form-item.filter-date_range) { grid-column: 1 / -1; }
  .sales-overview .filter-actions { grid-column: 1 / -1; }
}
@container sales-overview (min-width: 720px) and (max-width: 1250px) {
  .sales-overview .sales-filters { grid-template-columns: minmax(120px, 1fr) minmax(160px, 1.4fr) minmax(100px, .8fr) auto; }
  .sales-overview .filter-grid :deep(.el-form-item.filter-date_range) { grid-column: 1 / 4; }
  .sales-overview .filter-actions { grid-column: 4; grid-row: 2; }
}
@container sales-overview (max-width: 620px) {
  .sales-sku-report .filter-grid :deep(.el-form-item.filter-date_range) { grid-row: 3; }
  .sales-sku-report .filter-grid :deep(.el-form-item.filter-sku) { grid-column: 1 / -1; grid-row: 4; }
  .sales-sku-report .sales-filters .filter-actions { grid-column: 1 / -1; grid-row: 5; }
  .sales-overview .sales-filters { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .sales-overview .filter-grid :deep(.filter-store_id) { grid-column: 1 / -1; grid-row: 2; }
  .sales-overview .filter-grid :deep(.filter-currency) { grid-column: 2; grid-row: 1; }
  .sales-overview :deep(.filter-date_range .el-form-item__content) { flex-wrap: wrap; }
  .sales-overview :deep(.filter-date_range .el-date-editor) { flex-basis: 100%; min-width: 0; }
  .quick-dates { width: 100%; }
  .quick-dates button { flex: 1; height: 44px; padding: 0 4px; }
  .sales-store-report :deep(.el-table-fixed-column--left),
  .sales-store-report :deep(.el-table-fixed-column--right) { position: static !important; }
  .sales-store-report :deep(.el-table-fixed-column--left::before),
  .sales-store-report :deep(.el-table-fixed-column--right::before) { display: none; }
}
.sales-content, .table-panel { min-width: 0; }
.field-note { margin: 0 0 12px; color: #475569; font-size: 12px; line-height: 1.6; }
.numeric-value { font-variant-numeric: tabular-nums; white-space: nowrap; }
.raw-value { display: block; margin-top: 5px; color: #475569; font-size: 12px; }
.sales-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.sales-eyebrow { margin: 0 0 6px; color: #0f766e; font-size: 12px; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
.sales-header h1 { margin: 0; font-size: 26px; letter-spacing: -.02em; }
.sales-header p:not(.sales-eyebrow) { max-width: 720px; margin: 8px 0 0; color: #64748b; font-size: 14px; line-height: 1.6; }
.sales-header__actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.freshness-rail { display: grid; grid-template-columns: 200px 1fr; gap: 24px; padding: 15px 18px; border: 1px solid #cbdbe0; border-radius: 8px; background: #fff; }
.freshness-rail__lead { display: flex; align-items: center; gap: 12px; }
.freshness-rail__lead div { display: grid; gap: 3px; }
.freshness-rail small, .freshness-rail dt { color: #64748b; font-size: 11px; }
.freshness-rail strong { font-size: 15px; }
.status-dot { width: 11px; height: 11px; border: 3px solid #e2e8f0; border-radius: 50%; background: #64748b; box-shadow: 0 0 0 4px #f1f5f9; }
.status-dot.ready { background: #059669; box-shadow: 0 0 0 4px #d1fae5; }
.status-dot.partial, .status-dot.stale { background: #d97706; box-shadow: 0 0 0 4px #fef3c7; }
.freshness-rail dl { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; margin: 0; }
.freshness-rail dl div { min-width: 0; padding-left: 16px; border-left: 1px solid #e2e8f0; }
.freshness-rail dd { margin: 5px 0 0; color: #334155; font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
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
.metric-card small { color: #475569; font-size: 12px; line-height: 1.5; }
.metric-card > strong { display: block; margin-top: 16px; font-size: 25px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.metric-card em { color: #64748b; font-size: 11px; font-style: normal; font-weight: 500; letter-spacing: 0; }
.metric-card p { margin: 9px 0 0; color: #64748b; font-size: 11px; }
.metric-card p.up { color: #047857; } .metric-card p.down { color: #b45309; }
.sales-panel { padding: 17px; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.panel-heading h2 { margin: 0; font-size: 16px; }
.panel-heading p { margin: 5px 0 0; color: #475569; font-size: 12px; line-height: 1.5; }
.guided-empty { display: grid; justify-items: center; padding: 16px 0; }
.table-panel :deep(.el-table__row) { cursor: pointer; }
.table-panel :deep(.el-pagination) { justify-content: flex-end; margin-top: 16px; }
.detail-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin: 0 0 18px; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 8px; background: #e2e8f0; }
.detail-list div { min-width: 0; padding: 12px; background: #fff; }
.detail-list dt { color: #64748b; font-size: 11px; } .detail-list dd { margin: 5px 0 0; overflow-wrap: anywhere; font-size: 13px; }
.detail-lines { margin-bottom: 18px; } .detail-lines h3 { margin: 0 0 10px; font-size: 14px; }
.dialog-context { margin: 0 0 12px; color: #475569; font-size: 13px; }
@media (max-width: 1180px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .freshness-rail dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 820px) { .sales-header { flex-direction: column; } .sales-header__actions { flex-wrap: wrap; } .freshness-rail { grid-template-columns: 1fr; } .freshness-rail dl { grid-template-columns: 1fr 1fr; } .freshness-rail dl div { padding: 0; border: 0; } }
@media (max-width: 560px) { .metric-grid, .freshness-rail dl, .detail-list { grid-template-columns: 1fr; } .sales-header__actions { align-items: stretch; flex-direction: column; width: 100%; } }
.filter-grid :deep(.el-form-item:has(.el-date-editor)) { grid-column: span 2; }
.sales-workspace :deep(.el-input__inner::placeholder) { color: #64748b; }
@media (max-width: 560px) { .filter-grid { grid-template-columns: minmax(0, 1fr); } .filter-grid :deep(.el-form-item:has(.el-date-editor)) { grid-column: auto; } }
.sales-workspace:has(.order-filters) { container: sales-orders / inline-size; }
.order-filters { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; align-items: end; }
.order-filters .filter-grid { display: contents; }
.order-filters .filter-grid :deep(.el-form-item) { min-width: 0; margin: 0; }
.order-filters .filter-grid :deep(.filter-date_range),
.order-filters .filter-grid :deep(.filter-sku) { grid-column: span 2; }
.order-filters :deep(.el-form-item__label) { margin-bottom: 6px; font-size: 12px; color: #475569; }
.order-filters :deep(.el-date-editor) { min-width: 0; width: 100%; }
.order-filters .filter-actions { border: 0; padding: 0; gap: 8px; }
.order-filters .filter-actions :deep(.el-button + .el-button) { margin-left: 0; }
@container sales-orders (max-width: 1100px) {
  .order-filters { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
@container sales-orders (max-width: 720px) {
  .order-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .order-filters .filter-grid :deep(.filter-external_order_id),
  .order-filters .filter-actions { grid-column: 1 / -1; }
}
@container sales-orders (max-width: 420px) {
  .order-filters { padding: 12px; }
  .order-filters .filter-grid :deep(.el-form-item),
  .order-filters .filter-actions { grid-column: 1 / -1; }
  .order-filters .filter-actions :deep(.el-button) { min-height: 44px; flex: 1; }
}
</style>

