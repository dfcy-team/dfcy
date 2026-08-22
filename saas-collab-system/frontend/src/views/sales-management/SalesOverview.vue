<template>
  <Stage0Placeholder
    title="销售总览"
    api-path="pending: sales_management.overview"
    :fields="['销售额', '净销售额', '订单量', '销量', '客单价', '退款率', '最新数据时间']"
    :search-fields="['统计日期', '平台', '区域', '门店', '币种']"
    :actions="['查看指标明细占位', '申请导出占位']"
    :extra-items="['Shopee Mock', 'TikTok Shop Mock', '仅展示 pending 数据']"
  />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';
</script>
