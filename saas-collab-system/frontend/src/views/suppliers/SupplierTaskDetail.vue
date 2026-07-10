<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">供应商任务详情</h1>
        <p>API: GET /api/external/supplier/tasks/{id}/；POST /api/external/supplier/tasks/{id}/feedback/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert title="供应商只能查看和回填当前供应商自己的任务，真实过滤以后端 tenant_id + supplier_id 为准。" type="info" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>生产任务信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务编号">{{ detail.task_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="供应商ID">{{ detail.supplier_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="SKU">{{ detail.sku_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="生产数量">{{ detail.production_quantity || '-' }}</el-descriptions-item>
        <el-descriptions-item label="已完成数量">{{ detail.completed_quantity || 0 }}</el-descriptions-item>
        <el-descriptions-item label="预计出货日期">{{ detail.expected_ship_date || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="是否逾期">{{ detail.is_overdue ? '是' : '否' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>feedback form placeholder</template>
      <el-form label-width="120px">
        <el-form-item label="回填进度"><el-input :model-value="detail.completed_quantity" disabled /></el-form-item>
        <el-form-item label="回填说明"><el-input :model-value="detail.feedback_note" disabled /></el-form-item>
        <el-form-item label="异常说明"><el-input :model-value="detail.exception_note" disabled /></el-form-item>
      </el-form>
      <el-button disabled>提交回填占位</el-button>
    </el-card>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchSupplierTaskDetail } from '../../api/suppliers';

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
    const response = await fetchSupplierTaskDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || '供应商任务详情接口失败');
    detail.value = getDetail(response.data);
    status.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '供应商任务详情请求失败';
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
