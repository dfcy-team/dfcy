<template>
  <Stage0Placeholder
    title="SKU销售"
    api-path="pending: sales_management.skus"
    :fields="['SKU', '商品名称', '平台', '门店', '销量', '销售额', '净销售额', '退款量', '退款率', '动销天数', '库存风险引用']"
    :search-fields="['统计日期', '平台', '区域', '门店', 'SKU', '商品名称']"
    :actions="['查看 SKU 明细占位', '跳转订单占位', '查看库存风险占位', '申请导出占位']"
    :extra-items="['库存风险仅引用现有数据', '不提供库存调整或补货写回动作']"
  />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';
</script>
