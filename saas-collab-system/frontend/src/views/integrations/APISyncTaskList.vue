<template>
  <Stage0Placeholder title="API同步任务列表" api-path="pending: integrations.sync_tasks.list" :fields="fields" :search-fields="['任务编号', '平台', '店铺', '同步类型', '状态']" :actions="['创建同步任务占位', '重试占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['任务编号', '平台', '店铺', '同步类型', '状态', '上次同步时间', '下次同步时间', '重试次数'];
</script>
