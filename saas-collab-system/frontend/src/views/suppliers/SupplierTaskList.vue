<template>
  <Stage0Placeholder title="供应商任务列表" api-path="pending: external.supplier.tasks.list" :fields="fields" :search-fields="['任务编号', '供应商', '状态', '是否逾期']" :actions="['回填记录占位', '异常说明占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['任务编号', '供应商', '商品编码', '生产数量', '已完成数量', '预计出货日期', '状态', '是否逾期', '回填记录', '异常说明'];
</script>
