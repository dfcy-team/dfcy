<template>
  <Stage0Placeholder title="供应商出货详情" api-path="pending: external.supplier.shipments.detail" :fields="fields" :search-fields="['出货单号']" :actions="['图片附件占位', '采购确认按钮占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['出货单号', '出货数量', '箱数', '重量', '体积', '箱唛', '物流单', '图片附件占位', '采购确认按钮占位'];
</script>
