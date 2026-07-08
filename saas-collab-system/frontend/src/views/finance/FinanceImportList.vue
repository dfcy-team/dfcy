<template>
  <Stage0Placeholder title="财务导入列表" api-path="pending: finance.imports.list" :fields="fields" :search-fields="['导入编号', '状态', '授权状态']" :actions="['导入按钮占位', '财务授权检查占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['导入编号', '文件名占位', '状态', '授权状态', '错误信息', '创建时间'];
</script>
