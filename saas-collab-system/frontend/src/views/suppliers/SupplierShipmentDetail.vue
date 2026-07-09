<template>
  <section class="supplier-page">
    <header class="supplier-header">
      <div>
        <h1 class="page-title">供应商出货详情</h1>
        <p class="page-note">后续对接API路径：GET /api/external/supplier/shipments/{id}/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert title="仅展示当前供应商自己的出货记录；真实 supplier_id 过滤以后端为准，前端不做真实权限过滤。" type="info" show-icon :closable="false" />
    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

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
      <template #header>图片/箱唛/物流单附件占位</template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="附件占位字段">{{ detail.attachment_placeholder || 'demo/placeholder only' }}</el-descriptions-item>
      </el-descriptions>
      <el-upload class="upload-placeholder" action="#" disabled>
        <el-button disabled>选择附件占位</el-button>
      </el-upload>
    </el-card>

    <div class="supplier-actions">
      <el-button disabled>保存占位</el-button>
      <el-button type="primary" disabled>采购确认按钮占位</el-button>
    </div>

    <el-empty v-if="!loading && !errorMessage && !detail.id" description="暂无供应商出货详情" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchSupplierShipmentDetail } from '../../api/suppliers';

const route = useRoute();
const detail = ref({});
const loading = ref(false);
const errorMessage = ref('');
const warningMessage = ref('');
const dataStatus = ref('loading');

const statusTagType = computed(() => {
  if (dataStatus.value === 'mock') return 'info';
  if (dataStatus.value === 'fallback') return 'warning';
  if (dataStatus.value === 'error') return 'danger';
  return 'success';
});

function getDetail(data) {
  if (Array.isArray(data?.items)) return data.items[0] || {};
  return data || {};
}

async function loadSupplierShipmentDetail() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchSupplierShipmentDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || '供应商出货详情接口返回失败');

    detail.value = getDetail(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '供应商出货详情接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '供应商出货详情接口请求失败';
    detail.value = {};
  } finally {
    loading.value = false;
  }
}

onMounted(loadSupplierShipmentDetail);
</script>

<style scoped>
.supplier-page {
  display: grid;
  gap: 16px;
}

.supplier-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-note {
  margin: -8px 0 0;
  color: #64748b;
  font-size: 13px;
}

.supplier-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.upload-placeholder {
  margin-top: 12px;
}
</style>
