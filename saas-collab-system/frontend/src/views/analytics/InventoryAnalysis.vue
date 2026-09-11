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
    table-title="库存快照明细"
    table-note="每个仓库、来源 SKU 显示所选日期范围内的最新快照。点击表头升序、降序或取消排序，作用于全部筛选结果；风险升序为缺货、锁定偏高、低库存、正常；关联升序为未关联、已关联。"
  />
</template>

<script setup>
import { ref } from 'vue';
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchInventoryAnalysis } from '../../api/analytics';

const filters = ref([
  { key: 'date_range', label: '快照日期（UTC）', type: 'daterange' },
  { key: 'warehouse', label: '仓库', options: [] },
  { key: 'risk', label: '数量风险', options: [{ label: '缺货', value: 'out' }, { label: '低库存（1–5）', value: 'low' }, { label: '锁定偏高', value: 'locked' }, { label: '正常', value: 'healthy' }] }
]);

async function loadInventory(params) {
  const response = await fetchInventoryAnalysis(params);
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
  { prop: 'risk_label', label: '数量风险' },
  { prop: 'mapping_status', label: 'SKU 关联' },
  { prop: 'snapshot_time', label: '快照时间（UTC）', width: 190 }
].map((column) => ({ ...column, sortable: 'custom' }));
</script>
