<template>
  <div class="document-sku">
    <strong>{{ sku || '—' }}</strong>
    <small>旧 SKU：{{ legacySkuCode || '未维护' }}</small>
  </div>
</template>
<script setup>
defineProps({ sku: { type: String, default: '' }, legacySkuCode: { type: String, default: '' } });
</script>
<style scoped>
.document-sku{min-width:0;overflow-wrap:anywhere}.document-sku strong{font-weight:600}.document-sku small{display:block;margin-top:4px;font-size:12px;line-height:1.5;color:#64748b}
</style>
