<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="库存分析"
    subtitle="查看极风 WMS 最新库存快照、内部 SKU 关联与数量风险。"
    boundary-note="库存指标仅用于只读分析；风险列表不会自动补货或生成采购订单。"
    :loader="loadInventory"
    :filters="filters"
    :columns="columns"
    @reset="includeVirtual = false"
    quality-label="SKU 映射率"
    trend-title="在手库存历史快照"
    trend-note="按 UTC 日期统计各仓库 SKU 当天最后一次快照，不累加同日重复同步；缺少销量口径，暂不计算覆盖天数。"
    trend-unit="件"
    trend-empty-text="暂无历史库存快照。"
    table-title="库存快照明细"
    table-note="每个仓库、来源 SKU 显示所选日期范围内的最新快照。点击表头升序、降序或取消排序，作用于全部筛选结果；风险升序为缺货、锁定偏高、低库存、正常；关联升序为未关联、已关联。"
  >
    <template #after-quality="{ data }">
      <section class="inventory-signals" aria-label="库存风险与时效" v-if="data.risk_summary">
        <div><span>缺货 SKU</span><strong>{{ data.risk_summary.out_of_stock }}</strong></div>
        <div><span>低库存 SKU</span><strong>{{ data.risk_summary.low_stock }}</strong></div>
        <div><span>锁定偏高 SKU</span><strong>{{ data.risk_summary.locked_stock }}</strong></div>
        <div><span>快照时效</span><strong>{{ freshnessLabel(data.freshness?.status) }}</strong><small v-if="data.freshness?.age_hours != null">距最近同步 {{ data.freshness.age_hours }} 小时</small></div>
      </section>
      <p v-if="data.risk_summary" class="inventory-caveat">{{ data.definition?.replenishment_basis }} 当前 {{ data.risk_summary.data_insufficient }} 条仓库 SKU 不提供补货预测。</p>
    </template>
    <template #table-actions="{ search, loading }">
      <el-checkbox v-model="includeVirtual" :disabled="loading" @change="search"
        title="同时控制明细、库存汇总、风险统计和历史趋势；未设置属性或未关联的 SKU 仍保留。">
        包含虚拟商品
      </el-checkbox>
    </template>
  </Phase3AnalyticsPage>
</template>

<script setup>
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchInventoryAnalysis } from '../../api/analytics';

const includeVirtual = ref(false);
const route = useRoute();

const filters = ref([
  { key: 'date_range', label: '快照日期（UTC）', type: 'daterange' },
  { key: 'warehouse', label: '仓库', defaultValue: String(route?.query?.warehouse_id || ''), options: [] },
  { key: 'sku', label: '来源／内部 SKU', type: 'text', defaultValue: String(route?.query?.sku || ''), placeholder: '搜索 SKU' },
  { key: 'risk', label: '数量风险', options: [{ label: '缺货', value: 'out' }, { label: '低库存（1–5）', value: 'low' }, { label: '锁定偏高', value: 'locked' }, { label: '正常', value: 'healthy' }] },
  { key: 'mapping_status', label: 'SKU 关联', options: [{ label: '已关联', value: 'mapped' }, { label: '未关联', value: 'unmapped' }] }
]);

function freshnessLabel(status) {
  return { fresh: '新鲜', delayed: '延迟', stale: '已过期', pending: '暂无快照' }[status] || '暂无快照';
}

async function loadInventory(params, { signal } = {}) {
  const response = await fetchInventoryAnalysis({ ...params, include_virtual: includeVirtual.value }, { signal });
  if (response?.success) filters.value[1].options = response.data.warehouse_options || [];
  return response;
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
  { prop: 'pending_putaway_qty', label: '待上架（件）' },
  { prop: 'defective_qty', label: '残次（件）' },
  { prop: 'risk_label', label: '数量风险' },
  { prop: 'mapping_status', label: 'SKU 关联' },
  { prop: 'snapshot_time', label: '快照时间（UTC）', width: 190 }
].map((column) => ({ ...column, sortable: 'custom' }));
</script>

<style scoped>
.inventory-signals { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.inventory-signals > div { display: flex; flex-direction: column; gap: 4px; padding: 14px; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; }
.inventory-signals span, .inventory-signals small { color: #64748b; font-size: 12px; }
.inventory-signals strong { color: #0f172a; font-size: 22px; }
.inventory-caveat { margin: 0; color: #64748b; font-size: 12px; }
@media (max-width: 900px) { .inventory-signals { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px) { .inventory-signals { grid-template-columns: 1fr; } }
</style>
