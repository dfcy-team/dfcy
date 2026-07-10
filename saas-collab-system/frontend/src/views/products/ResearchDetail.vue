<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">新品市调详情</h1>
        <p>API: GET /api/internal/products/research/{id}/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>市调基础信息表单</template>
      <el-form :model="detail" label-width="130px">
        <el-form-item label="市调编号"><el-input :model-value="detail.research_no" disabled /></el-form-item>
        <el-form-item label="商品名称"><el-input :model-value="detail.product_name" disabled /></el-form-item>
        <el-form-item label="平台"><el-input :model-value="detail.platform" disabled /></el-form-item>
        <el-form-item label="竞品链接"><el-input :model-value="detail.competitor_url" disabled /></el-form-item>
        <el-form-item label="预估销量"><el-input :model-value="detail.estimated_sales" disabled /></el-form-item>
        <el-form-item label="预估毛利"><el-input :model-value="detail.estimated_gross_margin" disabled /></el-form-item>
        <el-form-item label="审批状态"><el-input :model-value="detail.approval_status" disabled /></el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>竞品资料区</template>
      <p>{{ detail.competitor_url || '-' }}</p>
      <p>风险点：{{ formatList(detail.risk_points) }}</p>
    </el-card>

    <el-card shadow="never">
      <template #header>附件上传占位</template>
      <el-upload action="#" disabled><el-button disabled>选择附件占位</el-button></el-upload>
    </el-card>

    <div class="fix-actions">
      <el-button disabled>保存草稿占位</el-button>
      <el-button type="primary" disabled>提交审批占位</el-button>
    </div>

    <el-empty v-if="!loading && !message && !detail.id" description="暂无市调详情" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchResearchDetail } from '../../api/products';

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

function formatList(value) {
  return Array.isArray(value) ? value.join(', ') : value || '-';
}

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchResearchDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || '新品市调详情接口失败');
    detail.value = getDetail(response.data);
    status.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '新品市调详情请求失败';
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
