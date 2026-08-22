<template>
  <Stage0Placeholder
    title="销售订单"
    api-path="pending: sales_management.orders"
    :fields="['平台', '区域', '门店', '平台订单号', '下单时间', '订单状态', '商品数量', '订单金额', '退款状态', '来源更新时间']"
    :search-fields="['下单时间', '平台', '区域', '门店', '平台订单号', '系统订单号', '订单状态', 'SKU']"
    :actions="['查看详情占位', '复制脱敏订单号占位', '申请导出占位']"
    :extra-items="['买家姓名/电话/地址默认脱敏', '不提供编辑、发货、取消或退款动作']"
  />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';
</script>
