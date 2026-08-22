<template>
  <Stage0Placeholder
    title="门店销售"
    api-path="pending: sales_management.stores"
    :fields="['平台', '区域', '门店', '授权/同步状态', '销售额', '净销售额', '订单量', '销量', '客单价', '退款率', '最后同步时间']"
    :search-fields="['统计日期', '平台', '区域', '门店', '币种口径']"
    :actions="['查看门店明细占位', '跳转订单占位', '跳转 SKU 占位', '申请导出占位']"
    :extra-items="['授权配置统一跳转 API 数据接入', '销售管理不重复配置密钥']"
  />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';
</script>
