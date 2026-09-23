<template>
  <main class="inventory-workbench">
    <header class="workbench-heading">
      <div>
        <h1>库存工作台</h1>
        <p>按业务视角核查极风 WMS 库存；所有数量均来自有权查看的最新快照。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新数据</el-button>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="workbench-message" />
    <el-alert v-else-if="data && data.freshness?.status === 'stale'" title="库存快照已过期，请先核对同步任务，再据此决策。" type="warning" show-icon :closable="false" class="workbench-message" />
    <div v-if="data" class="workbench-freshness">
      <span>数据范围：当前用户授权范围</span>
      <span>最近同步：{{ formatTime(data.refreshed_at) }}</span>
      <span>口径：每个站点／仓库／来源 SKU 的最新快照；风险计数按仓库 SKU 记录</span>
      <el-checkbox v-model="includeVirtual" :disabled="loading" @change="load">包含虚拟商品</el-checkbox>
    </div>

    <el-empty v-if="!loading && !error && data && !data.warehouses?.length" description="授权范围内暂无极风 WMS 库存快照" />
    <template v-if="data && data.warehouses?.length">
      <el-tabs v-model="perspective" class="workbench-perspectives" aria-label="业务视角" @tab-change="changePerspective">
        <el-tab-pane label="库存运营" name="operations" />
        <el-tab-pane label="商品运营" name="product" />
        <el-tab-pane label="库存主管" name="manager" />
      </el-tabs>

      <section class="workbench-summary" :aria-label="`${perspectiveLabel}重点指标`">
        <div v-for="metric in visibleMetrics" :key="metric.label" class="workbench-metric">
          <span>{{ metric.label }}</span><strong>{{ number(metric.value) }}</strong><small>{{ metric.note }}</small>
        </div>
      </section>

      <section class="workbench-charts">
        <div class="workbench-panel">
          <div class="panel-heading"><h2>{{ perspective === 'product' ? '未关联最多的前 8 仓' : '风险最多的前 8 仓' }}</h2><span>点击仓库筛选下方待核查清单</span></div>
          <div v-for="warehouse in chartWarehouses" :key="warehouse.warehouse_id" class="warehouse-chart-row">
            <button type="button" :class="{ selected: selectedWarehouse === warehouse.warehouse_id }" @click="selectWarehouse(warehouse.warehouse_id)">{{ warehouse.warehouse_name }}</button>
            <div class="warehouse-track" :aria-label="`${warehouse.warehouse_name} ${warehouseRisk(warehouse)} 个 SKU`">
              <div :style="{ width: `${Math.max(warehouseRisk(warehouse) / maxWarehouseRisk * 100, warehouseRisk(warehouse) ? 2 : 0)}%` }" />
            </div>
            <strong>{{ number(warehouseRisk(warehouse)) }}</strong>
          </div>
          <p v-if="!chartWarehouses.length" class="muted">暂无仓库数据。</p>
        </div>
        <div class="workbench-panel">
          <div class="panel-heading"><h2>近 {{ trend.length }} 日库存趋势</h2><span>每日最后一次快照；不是出入库流水</span></div>
          <div v-if="trend.length" class="trend-chart">
            <svg viewBox="0 0 600 180" role="img" aria-label="每日在手与可用库存趋势">
              <line x1="12" y1="154" x2="588" y2="154" stroke="#dfe6f1" />
              <polyline :points="linePoints('total')" fill="none" stroke="#2457a6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
              <polyline :points="linePoints('available')" fill="none" stroke="#18a27c" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <div class="trend-labels"><span>{{ trend[0]?.date }}</span><span><i class="legend-dot total" />在手 <i class="legend-dot available" />可用</span><span>{{ trend.at(-1)?.date }}</span></div>
          </div>
          <p v-else class="muted">暂无历史快照。</p>
        </div>
      </section>

      <section class="workbench-panel workbench-focus">
        <div class="panel-heading"><div><h2>{{ perspectiveLabel }}待核查清单</h2><span>展示 {{ data.focus?.length || 0 }} / {{ number(data.focus_total) }} 条；汇总指标统计整个授权范围</span></div><router-link v-if="canOpenAnalysis" to="/analytics/inventory">查看库存分析</router-link></div>
        <div class="focus-filters">
          <el-select v-model="selectedWarehouse" placeholder="全部仓库" clearable aria-label="筛选仓库" @change="load">
            <el-option v-for="warehouse in data.warehouses" :key="warehouse.warehouse_id" :label="warehouse.warehouse_name" :value="warehouse.warehouse_id" />
          </el-select>
          <el-input v-model.trim="skuSearch" clearable placeholder="来源或内部 SKU" aria-label="搜索 SKU" @keyup.enter="load" />
          <el-button type="primary" :loading="loading" @click="load">查询</el-button>
          <el-button @click="clearFocusFilters">重置筛选</el-button>
        </div>
        <el-table :data="data.focus || []" stripe empty-text="当前筛选范围内没有待核查记录" class="focus-table">
          <el-table-column prop="warehouse_name" label="仓库" min-width="130" />
          <el-table-column prop="source_sku" label="来源 SKU" min-width="155" />
          <el-table-column prop="internal_sku" label="内部 SKU" min-width="155"><template #default="{ row }">{{ row.internal_sku || '未关联' }}</template></el-table-column>
          <el-table-column prop="available_qty" label="可用" min-width="80" />
          <el-table-column prop="reserved_qty" label="占用" min-width="80" />
          <el-table-column label="数量风险" min-width="105"><template #default="{ row }"><el-tag :type="riskTag(row.risk)" size="small">{{ riskLabel(row.risk) }}</el-tag></template></el-table-column>
          <el-table-column label="SKU 关联" min-width="100"><template #default="{ row }">{{ row.mapping_status === 'mapped' ? '已关联' : '未关联' }}</template></el-table-column>
          <el-table-column label="快照时间" min-width="175"><template #default="{ row }">{{ formatTime(row.snapshot_at_utc) }}</template></el-table-column>
          <el-table-column label="操作" min-width="100"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">查看明细</el-button></template></el-table-column>
        </el-table>
      </section>
    </template>
    <el-drawer v-model="detailOpen" title="库存快照明细" size="min(440px, 100%)">
      <dl v-if="selectedRow" class="workbench-detail">
        <div><dt>仓库</dt><dd>{{ selectedRow.warehouse_name }}</dd></div>
        <div><dt>来源 SKU</dt><dd>{{ selectedRow.source_sku }}</dd></div>
        <div><dt>内部 SKU</dt><dd>{{ selectedRow.internal_sku || '未关联' }}</dd></div>
        <div><dt>可用库存</dt><dd>{{ number(selectedRow.available_qty) }} 件</dd></div>
        <div><dt>占用库存</dt><dd>{{ number(selectedRow.reserved_qty) }} 件</dd></div>
        <div><dt>数量风险</dt><dd>{{ riskLabel(selectedRow.risk) }}</dd></div>
        <div><dt>SKU 关联</dt><dd>{{ selectedRow.mapping_status === 'mapped' ? '已关联' : '未关联' }}</dd></div>
        <div><dt>快照时间</dt><dd>{{ formatTime(selectedRow.snapshot_at_utc) }}</dd></div>
      </dl>
      <router-link v-if="selectedRow && canOpenAnalysis" :to="{ path: '/analytics/inventory', query: { warehouse_id: selectedRow.warehouse_id, sku: selectedRow.source_sku } }">前往库存分析核对该 SKU</router-link>
    </el-drawer>
  </main>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { fetchInventoryWorkbench } from '../../api/analytics';
import { formatApiError } from '../../api/request';
import { canAccessPath } from '../../router/menu';
import { useAuthStore } from '../../stores/auth';
import { pinia } from '../../stores';

const auth = useAuthStore(pinia);
const perspective = ref('operations');
const includeVirtual = ref(false);
const selectedWarehouse = ref('');
const skuSearch = ref('');
const loading = ref(false);
const error = ref('');
const data = ref(null);
const selectedRow = ref(null);
const detailOpen = ref(false);
let requestController;

const canOpenAnalysis = computed(() => canAccessPath(auth.currentUser, '/analytics/inventory'));
const perspectiveLabel = computed(() => ({ operations: '库存运营', product: '商品运营', manager: '库存主管' }[perspective.value]));
const trend = computed(() => data.value?.trend || []);
const chartWarehouses = computed(() => [...(data.value?.warehouses || [])].sort((a, b) => warehouseRisk(b) - warehouseRisk(a)).slice(0, 8));
const maxWarehouseRisk = computed(() => Math.max(1, ...chartWarehouses.value.map(warehouseRisk)));
const visibleMetrics = computed(() => {
  const item = (label, value, note) => ({ label, value, note });
  const counts = data.value?.risk_counts || {};
  const mapping = data.value?.mapping_counts || {};
  const totals = data.value?.totals || {};
  if (perspective.value === 'product') return [item('未关联 SKU', mapping.unmapped, '优先核对商品映射'), item('已关联 SKU', mapping.mapped, '可按内部 SKU 汇总'), item('缺货 SKU', counts.out, '先核对来源 SKU'), item('可用库存', totals.available, 'WMS 最新快照 · 件')];
  if (perspective.value === 'manager') return [item('在手库存', totals.on_hand, 'WMS 最新快照 · 件'), item('可用库存', totals.available, '可分配数量 · 件'), item('风险 SKU', Number(counts.out || 0) + Number(counts.low || 0) + Number(counts.locked || 0), '缺货／低库存／锁定偏高'), item('未关联 SKU', mapping.unmapped, '影响分析可信度')];
  return [item('缺货 SKU', counts.out, '可用库存 ≤ 0'), item('低库存 SKU', counts.low, '可用库存 1–5'), item('锁定偏高 SKU', counts.locked, '占用大于可用'), item('未关联 SKU', mapping.unmapped, '需要核对 SKU 映射')];
});
function number(value) { return Number(value || 0).toLocaleString('zh-CN'); }
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) + ' UTC' : '暂无快照'; }
function riskLabel(value) { return ({ out: '缺货', low: '低库存', locked: '锁定偏高', healthy: '正常' })[value] || '待核查'; }
function riskTag(value) { return ({ out: 'danger', low: 'warning', locked: 'warning', healthy: 'success' })[value] || 'info'; }
function workbenchError(response) {
  const base = formatApiError(response);
  const detail = response?.data;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return base;
  const [field, raw] = Object.entries(detail)[0] || [];
  const message = Array.isArray(raw) ? raw.join('；') : raw;
  return field && typeof message === 'string' ? `${base}（${field}：${message}）` : base;
}
function warehouseRisk(row) { return Number(perspective.value === 'product' ? row.unmapped : row.at_risk) || 0; }
function selectWarehouse(id) { selectedWarehouse.value = selectedWarehouse.value === id ? '' : id; load(); }
function clearFocusFilters({ reload = true } = {}) { selectedWarehouse.value = ''; skuSearch.value = ''; if (reload) load(); }
function changePerspective() { clearFocusFilters({ reload: false }); load(); }
function openDetail(row) { selectedRow.value = row; detailOpen.value = true; }
function linePoints(field) {
  const values = trend.value.map((item) => Number(item[field]) || 0);
  const max = Math.max(1, ...trend.value.flatMap((item) => [Number(item.total) || 0, Number(item.available) || 0]));
  return values.map((value, index) => `${12 + index * 576 / Math.max(1, values.length - 1)},${154 - value * 130 / max}`).join(' ');
}
async function load() {
  requestController?.abort();
  const controller = new AbortController();
  requestController = controller;
  loading.value = true;
  error.value = '';
  data.value = null;
  detailOpen.value = false;
  try {
    const response = await fetchInventoryWorkbench({ include_virtual: includeVirtual.value, perspective: perspective.value, ...(selectedWarehouse.value ? { warehouse_id: selectedWarehouse.value } : {}), ...(skuSearch.value ? { sku: skuSearch.value } : {}) }, { signal: controller.signal });
    if (controller.signal.aborted) return;
    if (response?.success) data.value = response.data;
    else error.value = workbenchError(response);
  } catch (cause) {
    if (!controller.signal.aborted) error.value = cause?.message || '库存数据读取失败';
  } finally {
    if (requestController === controller) loading.value = false;
  }
}
onMounted(load);
onBeforeUnmount(() => requestController?.abort());
</script>

<style scoped>
.inventory-workbench { padding: 20px; color: #172b4a; }
.workbench-heading, .panel-heading, .workbench-freshness, .focus-filters { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.workbench-heading h1 { margin: 0 0 5px; font-size: 24px; }
.workbench-heading p, .panel-heading span, .workbench-metric small, .muted { color: #697b93; font-size: 13px; }
.workbench-heading p { margin: 0; }
.workbench-message { margin-top: 16px; }
.workbench-freshness { justify-content: flex-start; flex-wrap: wrap; padding: 12px 0; color: #526780; font-size: 13px; }
.workbench-freshness .el-checkbox { margin-left: auto; }
.workbench-perspectives { margin-top: 6px; }
.workbench-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0 0 16px; }
.workbench-metric { display: flex; flex-direction: column; min-height: 103px; padding: 15px 18px; border: 1px solid #dae3f0; border-radius: 6px; background: #fff; }
.workbench-metric > span { font-size: 14px; }
.workbench-metric strong { margin: 5px 0; font-size: 26px; line-height: 1; color: #244f92; }
.workbench-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }
.workbench-panel { min-width: 0; padding: 17px; background: #fff; border: 1px solid #dae3f0; border-radius: 6px; }
.panel-heading { margin-bottom: 18px; }
.panel-heading h2 { margin: 0; font-size: 16px; }
.panel-heading a, .focus-table a { color: #2874d0; text-decoration: none; }
.warehouse-chart-row { display: grid; grid-template-columns: minmax(70px, 100px) 1fr 45px; align-items: center; gap: 10px; min-height: 31px; font-size: 13px; }
.warehouse-chart-row button { border: 0; background: none; color: #3b5574; text-align: left; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.warehouse-chart-row button.selected { color: #2460ae; font-weight: 700; }
.warehouse-chart-row strong { text-align: right; }
.warehouse-track { height: 13px; background: #eef2f8; border-radius: 3px; overflow: hidden; }
.warehouse-track > div { height: 100%; background: #e97365; }
.trend-chart svg { display: block; width: 100%; height: 190px; }
.trend-labels { display: flex; justify-content: space-between; color: #6b7d96; font-size: 12px; }
.legend-dot { display: inline-block; width: 8px; height: 8px; margin: 0 4px; border-radius: 50%; }
.legend-dot.total { background: #2457a6; }.legend-dot.available { background: #18a27c; }
.focus-filters { justify-content: flex-start; flex-wrap: wrap; margin-bottom: 12px; }
.focus-filters .el-select { width: 180px; }.focus-filters .el-input { width: 250px; }
.workbench-detail { margin: 0 0 22px; }.workbench-detail > div { display: flex; justify-content: space-between; gap: 16px; padding: 11px 0; border-bottom: 1px solid #e7edf5; }.workbench-detail dt { color: #667b95; }.workbench-detail dd { margin: 0; font-weight: 600; text-align: right; overflow-wrap: anywhere; }
@media (max-width: 1000px) { .workbench-charts { grid-template-columns: 1fr; }.workbench-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .inventory-workbench { padding: 12px; }.workbench-heading { align-items: flex-start; }.workbench-freshness .el-checkbox { margin-left: 0; }.workbench-summary { grid-template-columns: 1fr 1fr; }.focus-filters .el-select, .focus-filters .el-input { width: 100%; } }
</style>
