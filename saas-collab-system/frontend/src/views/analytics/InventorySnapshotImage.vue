<template>
  <el-image v-if="source" class="inventory-snapshot-image" :src="source" :alt="alt"
    :preview-src-list="[source]" fit="contain" loading="lazy" preview-teleported @click.stop>
    <template #error><small>图片不可用</small></template>
  </el-image>
  <small v-else class="inventory-image-empty">暂无图片</small>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  url: { type: String, default: '' },
  alt: { type: String, default: '商品图片' }
});
const source = computed(() => /^(?:\/media\/[^/]|https?:\/\/)/i.test(props.url || '') ? props.url : '');
</script>

<style scoped>
.inventory-snapshot-image { width: 56px; height: 56px; vertical-align: middle; border-radius: 4px; }
.inventory-snapshot-image small, .inventory-image-empty { font-size: 11px; color: #667085; }
</style>
