<template>
  <Stage0Placeholder title="刊登模板列表" api-path="pending: listings.templates.list" :fields="fields" :search-fields="['平台', '国家', '类目']" :actions="['新增模板占位', '复制模板占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['商品编码', 'SKU', '平台', '国家', '店铺', '标题', '类目', '本地关键词', '描述', '尺码规则', '平台差异字段', '刊登状态', '页面价格状态', '生成RPA任务按钮占位'];
</script>
