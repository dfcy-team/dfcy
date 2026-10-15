<template>
  <div class="document-product-image">
    <el-image class="thumbnail" :src="imageUrl" :preview-src-list="imageUrl ? [imageUrl] : []" :alt="alt" :title="imageUrl ? '点击查看大图' : ''" fit="contain" preview-teleported>
      <template #error><span class="image-empty">{{ loading ? '图片加载中' : imagePath ? '图片暂不可用' : '暂无商品图片' }}</span></template>
    </el-image>
    <small v-if="imageUrl" class="zoom-hint">点击查看大图</small>
  </div>
</template>
<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { fetchApiFile } from '../../api/request';
const props = defineProps({ imagePath: { type: String, default: '' }, alt: { type: String, default: '商品图片' } });
const imageUrl = ref(''), loading = ref(false);
let sequence = 0;
function release() { if (imageUrl.value) URL.revokeObjectURL(imageUrl.value); imageUrl.value = ''; }
watch(() => props.imagePath, async path => {
  const current = ++sequence;
  release();
  const allowed = /^\/api\/(?:internal\/(?:supply-chain\/v2|commerce)|external\/supplier\/supply-chain\/v2)\/[^?#]*\/image\/$/.test(path);
  if (!allowed) { loading.value = false; return; }
  loading.value = true;
  try {
    const result = await fetchApiFile(path);
    if (current === sequence && result?.success) imageUrl.value = URL.createObjectURL(result.blob);
  } catch { /* Keep the placeholder if the authenticated image request fails. */ }
  finally { if (current === sequence) loading.value = false; }
}, { immediate: true });
onBeforeUnmount(() => { sequence++; release(); });
</script>
<style scoped>
.document-product-image{display:inline-flex;flex-direction:column;align-items:center;gap:4px;max-width:100%}.thumbnail{width:76px;height:76px;border:1px solid #e5e7eb;border-radius:8px}.image-empty{display:flex;align-items:center;justify-content:center;height:100%;font-size:11px;color:#667085;text-align:center}.zoom-hint{font-size:11px;line-height:1.4;color:#2563eb;white-space:nowrap}
</style>
