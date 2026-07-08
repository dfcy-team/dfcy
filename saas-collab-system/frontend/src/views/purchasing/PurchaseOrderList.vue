<template>
  <Stage0Placeholder title="采购订单列表" api-path="pending: purchasing.orders.list" :fields="fields" :search-fields="['采购单号', '商品编码', '供应商', '状态', '审批状态']" :actions="['新增采购单占位', '提交审批占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['采购单号', '商品编码', 'SKU', '供应商', '采购数量', '单价', '交期', '付款方式', '状态', '审批状态'];
</script>
