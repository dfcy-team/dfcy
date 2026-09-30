<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="库存分析"
    subtitle="查看极风 WMS 最新库存快照、内部 SKU 关联与数量风险。"
    boundary-note="库存指标仅用于只读分析；风险列表不会自动补货或生成采购订单。"
    :loader="loadInventory"
    :filters="filters"
    :columns="columns"
    quality-label="SKU 映射率"
    trend-title="在手库存历史快照"
    trend-note="按 UTC 日期统计各仓库 SKU 当天最后一次快照，不累加同日重复同步；缺少销量口径，暂不计算覆盖天数。"
    trend-unit="件"
    trend-empty-text="暂无历史库存快照。"
    @row-click="openInventoryRow"
    table-title="库存快照明细"
    :table-note="asOf ? '穿透模式：每个仓库、来源 SKU 取截止日期之前的最后快照，保留未在截止当天同步的 SKU。' : '每个仓库、来源 SKU 显示所选日期范围内的最新快照；点击行查看快照与成本版本，点击表头可对全部结果排序。'"
  >
    <template #table-actions="{ search, loading }">
      <el-checkbox v-model="includeVirtual" :disabled="loading" @change="search"
        title="同时控制明细、库存汇总、风险统计和历史趋势；未设置属性或未关联的 SKU 仍保留。">
        包含虚拟商品
      </el-checkbox>
    </template>
  </Phase3AnalyticsPage>
  <el-drawer v-model="snapshotOpen" title="库存历史快照" size="min(620px, 100vw)">
    <template v-if="selectedSnapshot">
      <p>快照时间（UTC）：{{ selectedSnapshot.snapshot_time || '未提供' }}</p>
      <dl class="snapshot-fields">
        <div v-for="column in columns" :key="column.prop"><dt>{{ column.label }}</dt><dd>{{ selectedSnapshot[column.prop] ?? '—' }}</dd></div>
      </dl>
      <section class="snapshot-context">
        <h3>查询条件</h3>
        <p>快照日期（UTC）：{{ historicalDateLabel(selectedFilters) }}</p>
        <p v-if="selectedFilters.warehouse">仓库：{{ selectedFilters.warehouse }}</p>
        <p v-if="selectedFilters.risk">数量风险：{{ selectedFilters.risk }}</p>
      </section>
      <el-button v-if="canOpenCostVersion" type="primary" @click="openCostVersion">查看成本版本</el-button>
    </template>
  </el-drawer>
</template>

<script>
export function historicalDateLabel(filters) {
  const range = filters?.date_range;
  return Array.isArray(range) && range.length === 2 ? `${range[0]} 至 ${range[1]}` : '未指定';
}

export function buildInventoryCostLocation(row, valuationAt) {
  const at=valuationAt || row.snapshot_at_utc || (row.snapshot_time ? (row.snapshot_time.endsWith('Z') ? row.snapshot_time : row.snapshot_time.replace(' ', 'T')+'Z') : null);
  return { query: { sku_id: row.internal_sku_id, ...(row.warehouse_id != null ? { warehouse_id: row.warehouse_id } : {}), ...(at ? { occurred_at: at } : {}) } };
}
</script>

<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchInventoryAnalysis } from '../../api/analytics';
import { canAccessPath } from '../../router/menu';
import { useAuthStore } from '../../stores/auth';

const router = useRouter();
const route = useRoute();
const includeVirtual = ref(route?.query?.include_virtual === 'true');
const asOf = computed(()=>route?.query?.as_of === 'true');
watch(()=>route?.query?.include_virtual,value=>{includeVirtual.value=value==='true';});
const auth = useAuthStore();
const snapshotOpen = ref(false);
const selectedSnapshot = ref(null);
const selectedFilters = ref({});
const canOpenCostVersion = computed(() => Boolean(selectedSnapshot.value?.internal_sku_id) && canAccessPath(auth.currentUser, '/products/costs'));

const filters = ref([
  { key: 'date_range', label: '快照日期（UTC）', type: 'daterange' },
  { key: 'warehouse', label: '仓库', options: [] },
  { key: 'sku', label: 'SKU', type: 'text' },
  { key: 'risk', label: '数量风险', options: [{ label: '缺货', value: 'out' }, { label: '低库存（1–5）', value: 'low' }, { label: '锁定偏高', value: 'locked' }, { label: '正常', value: 'healthy' }] }
]);

async function loadInventory(params, options) {
  const response = await fetchInventoryAnalysis({ ...params, inventory_type: route?.query?.inventory_type, unmapped_only: route?.query?.unmapped_only, sku_exact: route?.query?.sku_exact, site_code: route?.query?.site_code, as_of: asOf.value ? 'true' : undefined, include_virtual: includeVirtual.value }, options);
  if (response?.success) filters.value[1].options = response.data.warehouse_options || [];
  return response;
}

function openInventoryRow(row, appliedFilters = {}) {
  selectedSnapshot.value = row;
  selectedFilters.value = { ...appliedFilters };
  snapshotOpen.value = true;
}

function openCostVersion() {
  if (!canOpenCostVersion.value) return;
  router.push({ path: '/products/costs', ...buildInventoryCostLocation(selectedSnapshot.value, route?.query?.valuation_at) });
}

const columns = [
  { prop: 'source_sku', label: '来源 SKU', width: 190 },
  { prop: 'internal_sku', label: '内部 SKU', width: 160 },
  { prop: 'warehouse_name', label: '仓库名称', width: 150 },
  { prop: 'warehouse_code', label: '仓库编码' },
  { prop: 'on_hand_qty', label: '在手（件）' },
  { prop: 'available_qty', label: '可用（件）' },
  { prop: 'reserved_qty', label: '占用（件）' },
  { prop: 'in_transit_qty', label: '在途（件）' },
  { prop: 'risk_label', label: '数量风险' },
  { prop: 'mapping_status', label: 'SKU 关联' },
  { prop: 'snapshot_time', label: '快照时间（UTC）', width: 190 }
].map((column) => ({ ...column, sortable: 'custom' }));
</script>
