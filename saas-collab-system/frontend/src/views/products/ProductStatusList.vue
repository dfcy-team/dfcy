<template>
  <Stage0Placeholder title="商品状态列表" api-path="pending: products.status.list" :fields="fields" :search-fields="['商品编码', '生命周期状态', '销售状态']" :actions="['状态变更占位', '导出占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['商品编码', 'SPU', 'SKU', '商品名称', '生命周期状态', '销售状态', '编码冻结按钮占位'];
</script>
