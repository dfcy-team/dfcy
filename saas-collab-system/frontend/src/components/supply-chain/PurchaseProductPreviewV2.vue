<template>
  <div class="purchase-product-preview">
    <el-image class="product-image" :src="imageUrl" :preview-src-list="imageUrl ? [imageUrl] : []" fit="contain" preview-teleported :alt="`${sku} 商品图片`" :title="imageUrl ? '点击查看大图' : ''">
      <template #error><span class="image-empty">{{ loading ? '图片加载中' : imageSource ? '图片暂不可用' : '暂无商品图片' }}</span></template>
    </el-image>
    <div class="product-details">
      <div class="codes"><strong>{{ sku || '—' }}</strong><span>新编码</span><span>旧编码：{{ legacySkuCode || '未维护' }}</span></div>
      <div class="details-grid">
        <span v-for="field in fields" :key="field.label"><b>{{ field.label }}：</b>{{ field.value || '未维护' }}</span>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fetchApiFile } from '../../api/request';
const props = defineProps({ skuId: { type: [Number, String], required: true }, orderId: { type: [Number, String], default: null }, sku: { type: String, default: '' }, legacySkuCode: { type: String, default: '' }, productDetails: { type: Object, default: () => ({}) } });
const imageUrl = ref(''), loading = ref(false); let sequence = 0;
const imageSource = computed(() => String(props.productDetails?.image_url || '').trim());
const fields = computed(() => {
  const details = props.productDetails || {};
  const specValues = details.spec_values && typeof details.spec_values === 'object'
    ? Object.entries(details.spec_values).map(([key, value]) => `${key} ${value}`).join(' · ')
    : '';
  const dimensions = [details.package_length_cm, details.package_width_cm, details.package_height_cm].some(value => value !== null && value !== undefined && value !== '')
    ? [details.package_length_cm, details.package_width_cm, details.package_height_cm].map(value => value || '—').join(' × ') + ' cm'
    : '';
  return [
    { label: '规格', value: details.specification || specValues }, { label: '品牌', value: details.brand },
    { label: '颜色', value: details.color }, { label: '材质', value: details.material }, { label: '尺寸', value: details.size },
    { label: '包装尺寸', value: dimensions }, { label: '包装重量', value: details.package_weight_g ? `${details.package_weight_g} g` : '' },
  ];
});
function release() { if (imageUrl.value) URL.revokeObjectURL(imageUrl.value); imageUrl.value = ''; }
watch(() => [props.orderId, props.skuId, imageSource.value], async () => {
  const current = ++sequence; release();
  if (!imageSource.value) { loading.value = false; return; }
  loading.value = true;
  try {
    const imagePath = props.orderId
      ? `/api/internal/supply-chain/v2/purchase-orders/${encodeURIComponent(props.orderId)}/skus/${encodeURIComponent(props.skuId)}/image/`
      : `/api/internal/supply-chain/v2/options/skus/${encodeURIComponent(props.skuId)}/image/`;
    const result = await fetchApiFile(imagePath);
    if (current === sequence && result?.success) imageUrl.value = URL.createObjectURL(result.blob);
  } finally { if (current === sequence) loading.value = false; }
}, { immediate: true });
onBeforeUnmount(() => { sequence++; release(); });
</script>
<style scoped>
.purchase-product-preview{display:flex;gap:12px;align-items:flex-start;min-width:260px}.product-image{width:88px;height:88px;border:1px solid #e5e7eb;border-radius:8px;flex-shrink:0}.image-empty{display:flex;align-items:center;justify-content:center;height:100%;font-size:11px;color:#667085}.product-details{min-width:0}.codes{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin-bottom:6px}.codes span,.details-grid{font-size:12px;color:#64748b}.details-grid{display:grid;grid-template-columns:repeat(2,minmax(120px,1fr));gap:3px 10px}.details-grid b{font-weight:500;color:#475467}@media(max-width:650px){.purchase-product-preview{gap:8px}.product-image{width:68px;height:68px}.details-grid{grid-template-columns:1fr}}
</style>
