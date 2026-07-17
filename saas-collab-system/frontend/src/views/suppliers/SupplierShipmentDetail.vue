<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">供应商出货详情</h1>
        <p>API: GET /api/external/supplier/shipments/{id}/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert title="供应商只能查看和回填当前供应商自己的任务，真实过滤以后端 tenant_id + supplier_id 为准。" type="info" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>出货基础信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="出货单号">{{ detail.shipment_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="供应商ID">{{ detail.supplier_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="SKU">{{ detail.sku_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="出货数量">{{ detail.ship_quantity || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="物流单占位">{{ detail.tracking_no || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>箱规信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="箱数">{{ detail.carton_count || 0 }}</el-descriptions-item>
        <el-descriptions-item label="重量">{{ detail.weight || '-' }}</el-descriptions-item>
        <el-descriptions-item label="体积">{{ detail.volume || '-' }}</el-descriptions-item>
        <el-descriptions-item label="箱唛">{{ detail.shipping_mark || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>shipment form placeholder / 附件占位</template>
      <p>附件占位字段：{{ detail.attachment_placeholder || 'demo/placeholder only' }}</p>
      <el-upload action="#" disabled><el-button disabled>选择附件占位</el-button></el-upload>
    </el-card>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchSupplierShipmentDetail } from '../../api/suppliers';
import { apiState, detailData } from '../../utils/businessResponse';

const route = useRoute();
const detail = ref({});
const loading = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchSupplierShipmentDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || '供应商出货详情接口失败');
    detail.value = detailData(response.data);
    status.value = apiState(response.data);
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '供应商出货详情请求失败';
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
</style>
