<template>
  <Stage0Placeholder title="基础报表首页" api-path="pending: reports.basic.index" :fields="fields" :search-fields="['报表名称', '时间范围']" :actions="['查询占位', '导出占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['报表编号', '报表名称', '指标占位', '数据来源占位', '更新时间', '状态'];
</script>
