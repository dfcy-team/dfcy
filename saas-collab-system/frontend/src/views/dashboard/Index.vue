<template>
  <Stage0Placeholder title="首页" api-path="pending: dashboard.index" :fields="fields" :search-fields="['租户', '日期']" :actions="['刷新占位', '查看待办占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['系统状态', '待办任务', 'Mock接口状态', 'RPA任务概览', 'API同步概览', '财务授权提示'];
</script>
