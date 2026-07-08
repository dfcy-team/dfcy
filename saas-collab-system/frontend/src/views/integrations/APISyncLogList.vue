<template>
  <Stage0Placeholder title="API同步日志列表" api-path="pending: integrations.sync_logs.list" :fields="fields" :search-fields="['日志编号', '平台', '同步类型', '状态']" :actions="['查看详情占位', '导出占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['日志编号', '平台', '同步类型', '状态', '开始时间', '结束时间', '错误信息', '数据质量检查结果'];
</script>
