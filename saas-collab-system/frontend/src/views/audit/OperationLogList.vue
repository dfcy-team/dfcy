<template>
  <Stage0Placeholder title="操作日志列表" api-path="pending: audit.operation_logs.list" :fields="fields" :search-fields="['操作人', '模块', '动作', '对象ID']" :actions="['查看详情占位', '导出占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['操作人', '模块', '动作', '对象类型', '对象ID', 'IP', '时间'];
</script>
