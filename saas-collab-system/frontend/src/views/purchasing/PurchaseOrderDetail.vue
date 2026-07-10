<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">采购订单详情</h1>
        <p>API: GET /api/internal/purchasing/orders/{id}/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>采购基础信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="采购单号">{{ detail.po_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="SKU">{{ detail.sku_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="供应商ID">{{ detail.supplier_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="采购数量">{{ detail.quantity || '-' }}</el-descriptions-item>
        <el-descriptions-item label="单价">{{ detail.unit_price || '-' }}</el-descriptions-item>
        <el-descriptions-item label="交期">{{ detail.delivery_date || '-' }}</el-descriptions-item>
        <el-descriptions-item label="审批状态">{{ detail.approval_status || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>付款方式</template>
      <p>{{ detail.payment_terms || '-' }}</p>
    </el-card>

    <div class="fix-actions">
      <el-button disabled>审批按钮占位</el-button>
      <el-button type="primary" disabled>生成供应商生产任务占位</el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchPurchaseOrderDetail } from '../../api/purchasing';

const route = useRoute();
const detail = ref({});
const loading = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));

function getDetail(data) {
  if (Array.isArray(data?.items)) return data.items[0] || {};
  return data || {};
}

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchPurchaseOrderDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || '采购订单详情接口失败');
    detail.value = getDetail(response.data);
    status.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '采购订单详情请求失败';
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.fix-actions { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
