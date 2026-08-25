<template>
  <section class="sales-workspace" :aria-busy="loading">
    <header class="sales-header">
      <div>
        <h1>{{ contract.title }}</h1>
        <p>{{ contract.description }}</p>
      </div>
      <el-tag :type="mode === 'exports' ? 'info' : 'success'" effect="plain">
        {{ mode === 'exports' ? '本地模拟' : '数据已更新' }}
      </el-tag>
    </header>

    <template v-if="mode === 'exports'">
      <el-alert
        title="本页面不会创建 SaaS 后台导出任务，也不会向目标数据库写入数据。"
        type="info"
        show-icon
        :closable="false"
      />
      <section class="export-workspace">
        <div>
          <h2>从已查询数据生成文件</h2>
          <p>前往 API 数据接入选择平台、店铺和时间范围。完成查询后，可下载规范 CSV，并保留订单列表与订单详情原始 TXT。</p>
        </div>
        <el-button type="primary" @click="goToIntegrations">前往 API 控制台</el-button>
      </section>
    </template>

    <template v-else>
      <el-alert
        title="只读分析：本页面不会执行平台改价、退款、库存调整或订单状态写回。"
        type="info"
        show-icon
        :closable="false"
      />

      <section class="freshness-rail" aria-label="数据新鲜度与来源">
        <div class="freshness-lead">
          <span class="status-dot" :class="sourceStatus" />
          <div><small>数据新鲜度与来源</small><strong>{{ sourceStatusLabel }}</strong></div>
        </div>
        <dl>
          <div><dt>最近更新时间</dt><dd>{{ formatDateTime(refreshedAt) }}</dd></div>
          <div><dt>数据范围</dt><dd>租户 1 · 本机副本</dd></div>
          <div><dt>币种口径</dt><dd>按来源币种分别展示</dd></div>
          <div><dt>质量评分</dt><dd>{{ quality.score ?? '--' }} / 100</dd></div>
        </dl>
      </section>

      <el-form class="sales-filters" :model="query" label-position="top" @submit.prevent="applyFilters">
        <div class="filter-grid">
          <el-form-item v-for="filter in resolvedFilters" :key="filter.key" :label="filter.label">
            <el-date-picker
              v-if="filter.type === 'date'"
              v-model="query[filter.key]"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="年 /月/日"
            />
            <el-select
              v-else
              v-model="query[filter.key]"
              :placeholder="`全部${filter.label}`"
              @change="filter.key === 'platform' && onPlatformChange()"
            >
              <el-option value="" :label="`全部${filter.label}`" />
              <el-option v-for="option in filter.options" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </el-form-item>
          <div class="filter-actions">
            <el-button type="primary" native-type="submit" :loading="loading">应用筛选</el-button>
            <el-button @click="resetFilters">清空</el-button>
          </div>
        </div>
      </el-form>

      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

      <div v-loading="loading" class="sales-content">
        <section class="metric-grid" aria-label="销售核心指标">
          <article v-for="metric in metrics" :key="metric.code" class="metric-card">
            <span>{{ metric.label }}</span>
            <strong>{{ formatMetric(metric) }}</strong>
            <small>{{ metric.change || metric.definition || '当前筛选口径' }}</small>
          </article>
        </section>

        <div v-if="mode === 'overview'" class="overview-grid">
          <section class="sales-panel trend-panel">
            <div class="panel-heading"><h2>按日销售趋势</h2><strong>{{ trend.length }} 天</strong></div>
            <div v-if="trend.length" class="trend-list">
              <div v-for="point in trend" :key="point.date" class="trend-row">
                <time>{{ point.date }}</time>
                <div class="trend-track"><i :style="{ width: trendWidth(point.order_count) }" /></div>
                <b>{{ formatNumber(point.order_count) }} 单</b>
                <span>{{ formatMoneyMap(point.net_sales) }}</span>
              </div>
            </div>
            <el-empty v-else description="当前筛选范围没有趋势数据" :image-size="54" />
          </section>
          <section class="sales-panel observation-panel">
            <div class="panel-heading"><h2>数据观察</h2><strong>{{ quality.problem_rows || 0 }} 个问题</strong></div>
            <div v-if="quality.problem_rows" class="quality-warning">
              <strong>发现需要复核的数据</strong>
              <p>请在数据同步与质量页面查看问题摘要。</p>
            </div>
            <div v-else class="quality-good">
              <strong>未发现结构性问题</strong>
              <p>已检查 {{ formatNumber(quality.checked_rows || 0) }} 行本机 SaaS MySQL 数据。</p>
            </div>
          </section>
        </div>

        <div v-if="mode === 'data-quality'" class="quality-layout">
          <section class="sales-panel quality-panel">
            <div class="panel-heading"><h2>数据质量</h2><strong>{{ quality.score ?? '--' }} / 100</strong></div>
            <dl class="quality-summary">
              <div><dt>检查行数</dt><dd>{{ formatNumber(quality.checked_rows || 0) }}</dd></div>
              <div><dt>问题行数</dt><dd>{{ formatNumber(quality.problem_rows || 0) }}</dd></div>
            </dl>
            <div v-if="quality.problem_rows" class="quality-warning"><strong>存在质量问题</strong><p>请根据错误摘要核对来源数据。</p></div>
            <div v-else class="quality-good"><strong>全部检查通过</strong><p>当前数据可用于销售分析。</p></div>
          </section>
        </div>

        <section class="sales-panel table-panel">
          <div class="panel-heading">
            <h2>{{ contract.tableTitle }}</h2>
            <strong>{{ tableCountLabel }}</strong>
          </div>
          <el-table
            v-if="rows.length"
            :data="rows"
            :max-height="tableMaxHeight"
            @row-click="selectRow"
          >
            <el-table-column
              v-for="column in contract.columns"
              :key="column.prop"
              :label="column.label"
              :min-width="column.width || 96"
              :align="column.numeric ? 'right' : 'left'"
            >
              <template #default="{ row }">
                <div class="table-cell" :class="{ 'is-mono': column.mono }">
                  <el-tag v-if="isTagColumn(column)" :type="cellTagType(row, column)" effect="light" size="small">
                    {{ formatCell(row, column) }}
                  </el-tag>
                  <strong v-else-if="column.strong">{{ formatCell(row, column) }}</strong>
                  <span v-else>{{ formatCell(row, column) }}</span>
                  <small v-if="cellSecondary(row, column)">{{ cellSecondary(row, column) }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column v-if="mode === 'orders' || mode === 'returns'" label="" width="72" fixed="right">
              <template #default="{ row }"><el-button text type="primary" @click.stop="selectRow(row)">详情</el-button></template>
            </el-table-column>
          </el-table>
          <el-empty v-else :description="contract.emptyText" />
          <el-pagination
            v-if="total > pageSize"
            v-model:current-page="page"
            background
            layout="total, prev, pager, next"
            :page-size="pageSize"
            :total="total"
            @current-change="loadData"
          />
        </section>
      </div>

      <el-drawer v-model="detailOpen" size="620px" title="只读详情">
        <dl v-if="selectedRow" v-loading="detailLoading" class="detail-list">
          <div v-for="column in contract.columns" :key="column.prop"><dt>{{ column.label }}</dt><dd>{{ formatCell(selectedRow, column) }}</dd></div>
        </dl>
        <section v-if="selectedRow?.items?.length" class="detail-lines">
          <h3>商品与价格明细</h3>
          <el-table :data="selectedRow.items" size="small">
            <el-table-column prop="item_name_snapshot" label="商品" min-width="180" />
            <el-table-column prop="seller_sku" label="Seller SKU" min-width="130" />
            <el-table-column prop="quantity" label="数量" width="70" />
            <el-table-column prop="original_unit_price" label="原始单价" width="100" />
            <el-table-column prop="sale_unit_price" label="折扣单价" width="100" />
            <el-table-column prop="line_total_amount" label="行金额" width="100" />
          </el-table>
        </section>
      </el-drawer>
    </template>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { fetchSalesFilters, fetchSalesOrderDetail, fetchSalesPage } from '../../api/salesManagement';
import { formatApiError } from '../../api/request';
import { salesPageContracts } from './pageContracts';

const props = defineProps({ mode: { type: String, required: true } });
const router = useRouter();
const contract = computed(() => salesPageContracts[props.mode] || salesPageContracts.overview);
const query = reactive({});
const filterData = reactive({ platforms: [], stores: [], currencies: [] });
const loading = ref(false);
const errorMessage = ref('');
const rows = ref([]);
const metrics = ref([]);
const trend = ref([]);
const quality = ref({});
const sourceStatus = ref('pending');
const refreshedAt = ref('');
const total = ref(0);
const page = ref(1);
const selectedRow = ref(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
let requestSequence = 0;

const pageSize = computed(() => ['orders', 'returns', 'skus'].includes(props.mode) ? 50 : 100);
const tableMaxHeight = computed(() => ['orders', 'skus'].includes(props.mode) ? 620 : undefined);
const maxTrend = computed(() => Math.max(...trend.value.map((point) => Number(point.order_count) || 0), 1));
const sourceStatusLabel = computed(() => sourceStatus.value === 'ready' ? 'SaaS MySQL 已更新' : '等待首批数据');
const resolvedFilters = computed(() => contract.value.filters.map((filter) => ({
  ...filter,
  options: optionsFor(filter.optionSource)
})));
const tableCountLabel = computed(() => {
  if (props.mode === 'orders' || props.mode === 'returns') return `${formatNumber(total.value)} 单`;
  if (props.mode === 'stores' || props.mode === 'overview') return `${formatNumber(total.value)} 家店铺`;
  if (props.mode === 'skus') return `${formatNumber(rows.value.length)} 个 SKU`;
  if (props.mode === 'data-quality') return `${formatNumber(rows.value.length)} 个任务`;
  return `${formatNumber(total.value)} 条`;
});

function optionsFor(source) {
  if (!source) return [];
  if (source === 'stores') {
    return filterData.stores
      .filter((store) => !query.platform || store.platform === query.platform)
      .map((store) => ({ label: `${store.name} · ${store.region}`, value: store.id }));
  }
  const labels = { shopee: 'Shopee', tiktok: 'TikTok Shop', jifeng_wms: '极风 WMS' };
  return (filterData[source] || []).map((value) => {
    const code = typeof value === 'object' ? value.code : value;
    const name = typeof value === 'object' ? value.name : labels[value];
    return { label: name || code, value: code };
  });
}

function initializeFilters() {
  Object.keys(query).forEach((key) => delete query[key]);
  contract.value.filters.forEach((filter) => { query[filter.key] = ''; });
  page.value = 1;
}

async function loadFilterOptions() {
  if (props.mode === 'exports') return;
  const response = await fetchSalesFilters(query.platform ? { platform: query.platform } : {});
  if (!response?.success) return;
  Object.keys(filterData).forEach((key) => { filterData[key] = response.data?.[key] || []; });
}

function requestParams() {
  const params = { page: page.value, page_size: pageSize.value };
  Object.entries(query).forEach(([key, value]) => { if (value !== '' && value !== null) params[key] = value; });
  return params;
}

async function loadData() {
  if (props.mode === 'exports') return;
  const sequence = ++requestSequence;
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetchSalesPage(props.mode, requestParams());
    if (sequence !== requestSequence) return;
    if (!response?.success) throw new Error(formatApiError(response));
    const data = response.data || {};
    rows.value = props.mode === 'data-quality' ? (data.sources || []) : (data.results || []);
    total.value = Number(data.count ?? rows.value.length);
    metrics.value = data.summary_metrics || data.metrics || [];
    trend.value = data.trend || [];
    quality.value = data.quality || {};
    sourceStatus.value = data.source_status || (rows.value.length ? 'ready' : 'pending');
    refreshedAt.value = data.refreshed_at || data.quality?.refreshed_at || '';
  } catch (error) {
    errorMessage.value = error?.message || '销售数据加载失败';
    rows.value = [];
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function applyFilters() { page.value = 1; selectedRow.value = null; detailOpen.value = false; loadData(); }
function resetFilters() { initializeFilters(); loadFilterOptions(); loadData(); }
function onPlatformChange() { query.store_id = ''; loadFilterOptions(); }
function goToIntegrations() { router.push('/integrations/configs'); }

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : (value || '—');
}

function formatMoneyMap(value) {
  if (!value || typeof value !== 'object' || !Object.keys(value).length) return '—';
  const order = { THB: 1, MYR: 2, PHP: 3 };
  return Object.entries(value)
    .sort(([left], [right]) => (order[left] || 99) - (order[right] || 99))
    .map(([currency, amount]) => `${currency} ${formatNumber(amount)}`)
    .join(' · ');
}

function formatMetric(metric) {
  if (metric.money) return formatMoneyMap(metric.money);
  if (metric.value === null || metric.value === undefined || metric.value === '') return '—';
  if (typeof metric.value === 'number') return formatNumber(metric.value);
  return metric.value;
}

function formatDateTime(value) {
  if (!value) return '尚未同步';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : value;
}

function valueAt(row, path) { return path?.split('.').reduce((value, key) => value?.[key], row); }
function platformName(value) { return ({ shopee: 'Shopee', tiktok: 'TikTok Shop', jifeng_wms: '极风 WMS' }[value] || value || '—'); }
function statusName(value) {
  return ({ pending: '待处理', processing: '处理中', completed: '已完成', confirmed: '已确认', fulfilled: '履约中', cancelled: '已取消', success: '成功', partial_success: '部分成功', failed: '失败', idle: '空闲', disabled: 'disabled' }[value] || value || '—');
}

function formatCell(row, column) {
  const value = valueAt(row, column.prop);
  if (column.format === 'platform' || column.format === 'platform-resource') return platformName(value);
  if (column.format === 'date-time') return formatDateTime(value);
  if (column.format === 'row-money') return `${row.currency || '—'} ${formatNumber(value)}`;
  if (column.format === 'refund-money') return `${row.currency || '—'} ${formatNumber(value)}`;
  if (column.format === 'rate') return `${(Number(value || 0) * 100).toFixed(1)}%`;
  if (column.format === 'order-status') return statusName(value);
  if (column.format === 'return-status') return row.raw_status || statusName(value);
  if (column.format === 'refund-status') return row.normalized_status === 'cancelled' ? '已取消' : statusName(value);
  if (column.format === 'item-count') return formatNumber(value);
  if (column.format === 'return-type') return value || '—';
  if (column.format === 'sync-status' || column.format === 'authorization') return '已同步';
  if (column.format === 'sync-run-status') return statusName(value);
  if (column.format === 'fetched') return `${formatNumber(value || 0)} 条`;
  if (column.format === 'inventory-link') return value === 'mapped' ? '库存已关联' : '极风 WMS 待映射';
  return value === null || value === undefined || value === '' ? '—' : (column.numeric ? formatNumber(value) : value);
}

function cellSecondary(row, column) {
  if (column.format === 'item-count') return `${formatNumber(row.line_count || 0)} 个商品行`;
  if (column.format === 'refund-money') return `${formatNumber((row.items || []).reduce((sum, item) => sum + Number(item.quantity || 0), 0))} 件`;
  if (column.format === 'return-type') return row.requires_physical_return === null ? '退货状态未知' : (row.requires_physical_return ? '需要退货' : '仅退款');
  if (column.format === 'platform-resource') return row.resource === 'sales_order' ? '订单同步' : row.resource === 'refund_return' ? '退款退货同步' : '库存快照同步';
  const value = valueAt(row, column.secondary);
  if (value === null || value === undefined || value === '') return '';
  return `${column.secondaryPrefix || ''}${value}`;
}

function isTagColumn(column) {
  return ['order-status', 'return-status', 'sync-status', 'authorization', 'sync-run-status', 'inventory-link'].includes(column.format);
}

function cellTagType(row, column) {
  if (column.format === 'inventory-link') return valueAt(row, column.prop) === 'mapped' ? 'success' : 'warning';
  const value = valueAt(row, column.prop);
  if (['failed', 'cancelled'].includes(value)) return 'danger';
  if (['pending', 'processing', 'partial_success', 'disabled'].includes(value)) return 'warning';
  return 'success';
}

function trendWidth(value) { return `${Math.max(3, Number(value || 0) / maxTrend.value * 100)}%`; }

async function selectRow(row) {
  if (!['orders', 'returns'].includes(props.mode)) return;
  selectedRow.value = row;
  detailOpen.value = true;
  if (props.mode !== 'orders') return;
  detailLoading.value = true;
  const response = await fetchSalesOrderDetail(row.id);
  detailLoading.value = false;
  if (!response?.success) return ElMessage.error(formatApiError(response));
  selectedRow.value = response.data;
}

watch(() => props.mode, async () => {
  initializeFilters();
  if (props.mode === 'exports') return;
  await loadFilterOptions();
  await loadData();
}, { immediate: true });
</script>

<style scoped>
.sales-workspace { display: grid; gap: 16px; color: #10213d; }
.sales-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.sales-header h1 { margin: 0; font-size: 26px; letter-spacing: -.02em; }
.sales-header p { margin: 6px 0 0; color: #5c6f8f; font-size: 14px; }
.freshness-rail { display: grid; grid-template-columns: 240px 1fr; padding: 14px 16px; border: 1px solid #cfe1df; border-radius: 8px; background: #f8fcfb; }
.freshness-lead { display: flex; align-items: center; gap: 11px; }
.freshness-lead div { display: grid; gap: 3px; }
.freshness-rail small, .freshness-rail dt { color: #60718e; font-size: 11px; }
.freshness-rail strong { font-size: 13px; }
.status-dot { width: 9px; height: 9px; border: 5px solid #c9fae7; border-radius: 50%; background: #16b881; }
.status-dot.pending { border-color: #e2e8f0; background: #94a3b8; }
.freshness-rail dl { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0; }
.freshness-rail dl div { padding: 0 16px; border-left: 1px solid #dde7ee; }
.freshness-rail dd { margin: 5px 0 0; color: #10213d; font-size: 13px; }
.sales-filters { padding: 13px 16px; border: 1px solid #d7e0eb; border-radius: 8px; background: #fff; }
.filter-grid { display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)) auto; align-items: end; gap: 12px; }
.filter-grid :deep(.el-form-item) { margin: 0; }
.filter-grid :deep(.el-date-editor), .filter-grid :deep(.el-select) { width: 100%; }
.filter-actions { display: flex; gap: 8px; padding-bottom: 1px; }
.sales-content { display: grid; gap: 16px; min-height: 260px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-card { display: grid; align-content: start; min-height: 124px; padding: 16px; border: 1px solid #d7e0eb; border-radius: 8px; background: #fff; }
.metric-card span { font-size: 13px; font-weight: 650; }
.metric-card strong { margin-top: 18px; font-size: 26px; line-height: 1.12; font-variant-numeric: tabular-nums; letter-spacing: -.03em; }
.metric-card small { margin-top: 14px; color: #64789b; font-size: 11px; }
.overview-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr); gap: 16px; }
.sales-panel, .export-workspace { padding: 16px; border: 1px solid #d7e0eb; border-radius: 8px; background: #fff; }
.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.panel-heading h2 { margin: 0; font-size: 17px; }
.panel-heading > strong { font-size: 12px; }
.trend-list { display: grid; gap: 9px; }
.trend-row { display: grid; grid-template-columns: 88px minmax(120px, 1fr) 66px minmax(150px, auto); align-items: center; gap: 10px; color: #62728c; font-size: 11px; }
.trend-row b { color: #10213d; font-variant-numeric: tabular-nums; text-align: right; }
.trend-row > span { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.trend-track { height: 9px; overflow: hidden; background: #edf1f5; }
.trend-track i { display: block; height: 100%; background: #16877f; }
.quality-good, .quality-warning { padding-top: 28px; }
.quality-good strong { color: #079669; font-size: 17px; }
.quality-warning strong { color: #c47a13; font-size: 17px; }
.quality-good p, .quality-warning p { margin: 6px 0 0; color: #63728a; }
.quality-layout { display: grid; grid-template-columns: minmax(520px, 2fr) 1fr; }
.quality-panel { min-height: 220px; }
.quality-summary { display: grid; grid-template-columns: repeat(2, 1fr); margin: 0; border: 1px solid #d7e0eb; }
.quality-summary div { padding: 14px; }
.quality-summary div + div { border-left: 1px solid #d7e0eb; }
.quality-summary dt { color: #63728a; font-size: 11px; }
.quality-summary dd { margin: 8px 0 0; font-size: 24px; font-weight: 750; }
.table-panel { min-width: 0; }
.table-panel :deep(.el-table__header th) { background: #f4f7fa; color: #394962; font-size: 12px; }
.table-panel :deep(.el-table__row) { cursor: default; }
.table-panel :deep(.el-pagination) { justify-content: flex-end; margin-top: 16px; }
.table-cell { display: grid; gap: 4px; color: #10213d; line-height: 1.3; }
.table-cell small { color: #64748b; font-size: 10px; }
.table-cell.is-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.export-workspace { display: flex; align-items: center; justify-content: space-between; gap: 28px; padding: 22px; }
.export-workspace h2 { margin: 0; font-size: 18px; }
.export-workspace p { max-width: 760px; margin: 7px 0 0; color: #5c6f8f; line-height: 1.6; }
.detail-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin: 0 0 18px; overflow: hidden; border: 1px solid #e2e8f0; background: #e2e8f0; }
.detail-list div { padding: 12px; background: #fff; }
.detail-list dt { color: #64748b; font-size: 11px; }
.detail-list dd { margin: 5px 0 0; overflow-wrap: anywhere; }
.detail-lines h3 { font-size: 15px; }
@media (max-width: 1250px) { .filter-grid { grid-template-columns: repeat(3, 1fr); } .filter-actions { align-self: end; } }
@media (max-width: 900px) { .metric-grid { grid-template-columns: repeat(2, 1fr); } .overview-grid, .freshness-rail { grid-template-columns: 1fr; } .freshness-rail dl { margin-top: 14px; } }
@media (max-width: 640px) { .filter-grid, .metric-grid, .freshness-rail dl, .quality-summary { grid-template-columns: 1fr; } .overview-grid { grid-template-columns: 1fr; } .trend-row { grid-template-columns: 80px 1fr 56px; } .trend-row > span { display: none; } .sales-header, .export-workspace { align-items: stretch; flex-direction: column; } }
</style>
