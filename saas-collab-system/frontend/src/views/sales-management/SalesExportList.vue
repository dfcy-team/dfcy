<template>
  <Stage0Placeholder
    title="销售明细导出"
    api-path="pending: sales_management.exports"
    :fields="['任务编号', '申请人', '数据范围', '筛选条件', '记录数', '脱敏状态', '任务状态', '创建时间', '完成时间']"
    :search-fields="['任务编号', '申请人', '任务状态', '创建时间']"
    :actions="['创建导出任务占位', '下载脱敏文件占位', '查看审计占位']"
    :extra-items="['导出范围受租户、角色和门店授权约束', '下载文件不包含凭证或完整客户隐私数据']"
  />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';
</script>
