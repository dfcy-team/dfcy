<template>
  <Stage0Placeholder title="商品主数据详情" api-path="pending: products.master.detail" :fields="fields" :search-fields="['商品编码', 'SKU']" :actions="['保存占位', '编码冻结按钮占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['商品编码', 'SPU', 'SKU', '商品名称', '类目', '图片', '尺码', '材质', '卖点', '箱规重量', '生命周期状态', '销售状态', '编码冻结按钮占位'];
</script>
