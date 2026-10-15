<template><DocumentProductImageV2 :image-path="imagePath" /></template>
<script setup>
import { computed } from 'vue';
import DocumentProductImageV2 from './DocumentProductImageV2.vue';
const props = defineProps({ skuId: { type: [Number, String], required: true }, source: { type: String, default: '' }, procurement: { type: Boolean, default: false } });
const imagePath = computed(() => {
  if (!props.skuId || !props.source) return '';
  const base = props.procurement ? '/api/internal/supply-chain/v2/options' : '/api/internal/commerce/operating-options';
  return `${base}/skus/${encodeURIComponent(props.skuId)}/image/`;
});
</script>
