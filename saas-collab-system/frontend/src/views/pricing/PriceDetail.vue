<template>
  <Stage0Placeholder title="价格详情" api-path="pending: pricing.prices.detail" :fields="fields" :search-fields="['商品编码', 'SKU']" :actions="['提交价格审批按钮占位', '保存草稿占位']" />
</template>

<script setup>
import Stage0Placeholder from '../_Stage0Placeholder.vue';

const fields = ['采购成本', '物流成本', '平台佣金', '汇率', '目标毛利', '建议价', '审批价', '清仓价占位', '页面价', '提交价格审批按钮占位'];
</script>
