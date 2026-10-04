<template>
  <section v-if="isShopeeProductJob" class="product-order-gaps" aria-label="商品关联订单缺口预览">
    <h3>商品关联订单缺口</h3>
    <p>只读检查本店已持久化订单中的商品关联，不调用平台接口、不修改数据。预览由你手动启动。</p>
    <p v-if="beforeSummary || afterSummary" class="reconciliation-summary">
      最近一次运行：补采阶段前缺少关联 {{ count(beforeSummary?.missing_pairs) }} 对，补采后 {{ afterSummary ? count(afterSummary.missing_pairs) : '尚未完成校验' }} 对；
      尝试商品 {{ count(reconciliation?.attempted_products) }} 个，平台未返回 {{ count(reconciliation?.unavailable_products) }} 个，剩余冲突 {{ count(afterSummary?.conflict_pairs ?? beforeSummary?.conflict_pairs) }} 对。
      平台未返回或已删除的商品可能仍无法补齐。
    </p>
    <el-button v-if="canView" :disabled="loading" :loading="loading" @click="loadPreview">只读预览当前缺口</el-button>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="preview">
      <p class="gap-summary">
        源订单 {{ count(preview.summary?.source_rows) }} 行，去重商品关联 {{ count(preview.summary?.unique_pairs) }} 对，
        已关联 {{ count(preview.summary?.linked_pairs) }} 对，缺少 {{ count(preview.summary?.missing_pairs) }} 对。
        缺少商品 {{ count(preview.summary?.missing_product_ids) }} 个，缺少变体 {{ count(preview.summary?.missing_variant_pairs) }} 对，
        冲突 {{ count(preview.summary?.conflict_pairs) }} 对，无效标识 {{ count(preview.summary?.invalid_pairs) }} 对，零变体 {{ count(preview.summary?.zero_variant_pairs) }} 对。
      </p>
      <p v-if="preview.summary?.watermark">统计水位：{{ preview.summary.watermark }}</p>
      <p v-if="preview.notice">{{ preview.notice }}</p>
      <el-table v-if="preview.samples?.length" :data="preview.samples" size="small" border>
        <el-table-column prop="product_id" label="商品 ID" />
        <el-table-column prop="variant_id" label="变体 ID" />
        <el-table-column label="缺口原因"><template #default="{ row }">{{ reasonLabel(row.reason) }}</template></el-table-column>
        <el-table-column prop="item_rows" label="订单明细行数" />
      </el-table>
      <p v-else>本次只读检查未发现样本缺口。</p>
      <p>策略：{{ policyLabel(preview.policy) }}。预览最多展示 20 条样本。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { requestApi } from '../api/request';
import { syncError } from '../utils/syncPresentation';

const props = defineProps({ job: { type: Object, required: true }, canView: Boolean });
const isShopeeProductJob = computed(() => props.job.resource_type === 'platform_product' && String(props.job.platform || '').toLowerCase() === 'shopee');
const reconciliation = computed(() => props.job.order_product_reconciliation || null);
const beforeSummary = computed(() => reconciliation.value?.before_summary || reconciliation.value?.before || null);
const afterSummary = computed(() => reconciliation.value?.after_summary || reconciliation.value?.after || null);
const loading = ref(false);
const error = ref('');
const preview = ref(null);
let requestSequence = 0;

watch(() => props.job.id, () => {
  requestSequence += 1;
  preview.value = null;
  error.value = '';
  loading.value = false;
});

function count(value) { return Number.isFinite(Number(value)) ? Number(value) : 0; }
function policyLabel(value) {
  return ({ catalog_only: '仅常规商品同步', catalog_and_order_missing: '常规同步后补齐缺失关联', order_missing_only: '仅补齐缺失关联' })[value] || '未提供';
}
function reasonLabel(value) {
  return ({ product_missing: '商品缺失', variant_missing: '变体缺失', identity_conflict: '身份冲突', invalid_identity: '标识无效' })[value] || '其他';
}
async function loadPreview() {
  if (!props.canView || !isShopeeProductJob.value || loading.value) return;
  const sequence = ++requestSequence;
  const jobId = props.job.id;
  loading.value = true;
  error.value = '';
  preview.value = null;
  try {
    const response = await requestApi({ method: 'get', url: `/api/internal/integrations/sync-jobs/${jobId}/product-gaps/`, timeout: 60000 });
    if (!response.success) throw new Error(response.message || '读取商品关联缺口失败');
    if (sequence !== requestSequence || jobId !== props.job.id) return;
    preview.value = response.data;
  } catch (e) {
    if (sequence === requestSequence && jobId === props.job.id) error.value = syncError(e.message);
  } finally {
    if (sequence === requestSequence && jobId === props.job.id) loading.value = false;
  }
}
</script>

<style scoped>
.product-order-gaps { margin-top: 20px; padding-top: 16px; border-top: 1px solid #dbe3ec; }
h3 { margin: 0; font-size: 16px; }
p { color: #475569; font-size: 13px; line-height: 1.6; }
.reconciliation-summary, .gap-summary { padding: 10px 12px; border-radius: 6px; background: #f1f5f9; }
</style>
