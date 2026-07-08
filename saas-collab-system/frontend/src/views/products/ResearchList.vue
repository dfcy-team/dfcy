<template>
  <Stage0Placeholder title="新品市调列表" api-path="pending: products.research.list" :fields="fields" :search-fields="['市调编号', '商品名称', '平台', '审批状态']" :actions="['新增市调占位', '附件占位', '审批按钮占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['市调编号', '商品名称', '平台', '竞品链接', '预估销量', '预估毛利', '风险点', '附件占位', '审批状态占位'];
</script>
