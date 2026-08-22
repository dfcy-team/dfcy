<template>
  <Stage0Placeholder
    title="退款退货"
    api-path="pending: sales_management.returns"
    :fields="['平台', '门店', '平台订单号', '退款/退货单号', '类型', '原因', '退款金额', '处理状态', '发生时间', '同步时间']"
    :search-fields="['发生日期', '平台', '区域', '门店', '退款类型', '原因', '处理状态']"
    :actions="['查看订单占位', '查看原因分析占位', '申请导出占位']"
    :extra-items="['只读退款、退货、取消数据', '不提供平台退款或状态写回动作']"
  />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';
</script>
