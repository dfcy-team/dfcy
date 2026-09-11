<template>
  <section class="report-table" :aria-label="title">
    <header><div><h2>{{ title }}</h2><p>{{ skuReport ? '店铺 SKU 保留来源门店；商品 SKU 仅合并已关联的内部 SKU，未关联记录不跨店合并。' : '按日期与币种分别核对订单；退款使用申请日期，不与取消订单混同。' }}</p></div><details><summary>展示列</summary><div class="column-picker"><label v-for="column in columns" :key="column.prop"><input v-model="visible" type="checkbox" :value="column.prop">{{ column.label }}</label></div></details></header>
    <el-table :data="rows" stripe empty-text="当前筛选范围暂无记录，请调整条件或检查数据同步。" @sort-change="$emit('sort', $event)">
      <el-table-column v-if="skuReport" label="产品名称 / SKU" min-width="260"><template #default="{ row }"><div class="product"><strong>{{ row.product_name || '商品名称未提供' }}</strong><span>店铺 SKU：{{ row.seller_sku || '—' }}</span><span>内部 SKU：{{ row.internal_sku || '未关联' }}</span></div></template></el-table-column>
      <el-table-column v-else prop="date" label="日期" min-width="130" sortable />
      <el-table-column v-for="column in columns.filter(item => visible.includes(item.prop))" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 150" :align="column.numeric ? 'right' : 'left'" :sortable="skuReport ? (sortableSku.includes(column.prop) ? 'custom' : false) : true" :sort-method="(a,b) => compare(a,b,column)" show-overflow-tooltip><template #default="{ row }">{{ formatField(row[column.prop], column) }}</template></el-table-column>
    </el-table>
    <p class="report-note">金额按来源币种展示，不跨币种合计；“—”表示未提供。包裹、客户、毛营收、补贴、商品图片及同期对比暂无数据，不推算。</p>
  </section>
</template>
<script setup>
import { ref } from 'vue';
import { formatField } from './display';
const props = defineProps({ rows: { type: Array, default: () => [] }, skuReport: Boolean, title: { type: String, default: '汇总明细' } });
defineEmits(['sort']);
const money = (prop,label) => ({ prop,label,numeric:true,format:'money' });
const count = (prop,label) => ({ prop,label,numeric:true });
const columns = props.skuReport ? [
  {prop:'store_name',label:'门店',width:200},{prop:'platform_product_id',label:'平台商品 ID'},{prop:'platform_variant_id',label:'平台规格 ID'}, {prop:'variation',label:'变种',width:190}, {prop:'currency',label:'币种',width:85},
  money('gross_sales','非取消商品销售额'),count('valid_order_count','非取消订单数'),count('units_sold','非取消商品销量'),money('average_price','产品平均价格'),money('total_sales','全部商品销售额'),count('total_units','全部商品销量'),count('order_count','订单总量'),money('refund_amount','退款产品金额'),count('refund_units','退款产品数'),money('cancelled_amount','取消商品金额'),count('cancelled_units','取消商品数量'),count('cancelled_order_count','取消订单数'),{prop:'mapping_status',label:'SKU 关联',format:'enum'}
] : [{prop:'currency',label:'币种',width:85},count('order_count','订单总量'),count('valid_order_count','非取消订单数'),money('gross_sales','非取消订单销售额'),money('total_sales','全部订单金额'),money('average_order_value','平均订单金额'),money('refund_amount','退款申请金额'),count('refund_case_count','退款售后单数'),money('cancelled_amount','取消订单金额'),count('cancelled_order_count','取消订单数'),money('net_sales','净销售额')];
const visible = ref(columns.map(column=>column.prop));
const sortableSku = ['store_name','currency','gross_sales','valid_order_count','units_sold','average_price','total_sales','total_units','order_count','refund_amount','refund_units','cancelled_amount','cancelled_units','cancelled_order_count'];
function compare(a,b,column) { const left=a[column.prop],right=b[column.prop]; if(left==null)return 1;if(right==null)return -1;return column.numeric ? Number(left)-Number(right) : String(left).localeCompare(String(right)); }
</script>
<style scoped>
.report-table{min-width:0;background:#fff;border:1px solid #dce3ec;border-radius:6px;padding:18px;color:#172033}.report-table header{display:flex;justify-content:space-between;align-items:start;gap:16px;margin-bottom:14px}.report-table h2{font-size:15px;margin:0}.report-table p{font-size:12px;line-height:1.7;color:#475569}.report-table details{max-width:50%;text-align:right;font-size:12px}.report-table summary{cursor:pointer;color:#513ab9}.column-picker{display:flex;flex-wrap:wrap;gap:10px;padding:12px 0;justify-content:flex-end}.column-picker label{white-space:nowrap}.product{display:grid;gap:5px;padding:8px 0;line-height:1.6;overflow-wrap:anywhere}.product strong{font-weight:500}.product span{font-size:12px;color:#475569}.report-note{margin:14px 0 0}@media(max-width:600px){.report-table{padding:12px}.report-table header{flex-wrap:wrap}.report-table details{max-width:100%}}
</style>
