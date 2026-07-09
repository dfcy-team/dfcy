<template>
  <section class="ops-page">
    <header class="ops-header">
      <div>
        <h1 class="page-title">采购订单详情</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/purchasing/orders/{id}/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>采购基础信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="采购单号">{{ detail.po_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="交期">{{ detail.delivery_date || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建人">{{ detail.created_by_id || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>商品明细</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="SKU">{{ detail.sku_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="采购数量">{{ detail.quantity || '-' }}</el-descriptions-item>
        <el-descriptions-item label="单价">{{ detail.unit_price || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>供应商信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="供应商ID">{{ detail.supplier_id || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>付款方式</template>
      <p class="plain-value">{{ detail.payment_terms || '-' }}</p>
    </el-card>

    <el-card shadow="never">
      <template #header>审批状态占位</template>
      <el-tag>{{ detail.approval_status || 'pending' }}</el-tag>
    </el-card>

    <div class="ops-actions">
      <el-button disabled>保存草稿占位</el-button>
      <el-button disabled>审批按钮占位</el-button>
      <el-button type="primary" disabled>生成供应商生产任务按钮占位</el-button>
    </div>

    <el-empty v-if="!loading && !errorMessage && !detail.id" description="暂无采购订单详情" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchPurchaseOrderDetail } from '../../api/purchasing';

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

async function loadPurchaseOrderDetail() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchPurchaseOrderDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || '采购订单详情接口返回失败');

    detail.value = getDetail(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '采购订单详情接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '采购订单详情接口请求失败';
    detail.value = {};
  } finally {
    loading.value = false;
  }
}

onMounted(loadPurchaseOrderDetail);
</script>

<style scoped>
.ops-page {
  display: grid;
  gap: 16px;
}

.ops-header {
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

.ops-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.plain-value {
  margin: 0;
  color: #334155;
}
</style>
