<template>
  <section class="product-page">
    <header class="product-header">
      <div>
        <h1 class="page-title">新品市调详情</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/products/research/{id}/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>市调基础信息表单</template>
      <el-form :model="detail" label-width="120px">
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
      <el-descriptions :column="2" border>
        <el-descriptions-item label="竞品链接">{{ detail.competitor_url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="风险点">{{ formatList(detail.risk_points) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>附件上传占位</template>
      <el-upload action="#" disabled>
        <el-button disabled>选择附件占位</el-button>
      </el-upload>
    </el-card>

    <div class="product-actions">
      <el-button disabled>保存草稿占位</el-button>
      <el-button type="primary" disabled>提交审批按钮占位</el-button>
    </div>

    <el-empty v-if="!loading && !errorMessage && !detail.id" description="暂无商品市调详情" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchResearchDetail } from '../../api/products';

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

function formatList(value) {
  if (Array.isArray(value)) return value.join(', ');
  return value || '-';
}

async function loadResearchDetail() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchResearchDetail(route.params.id || 1);
    if (!response.success) {
      throw new Error(response.message || '商品市调详情接口返回失败');
    }

    detail.value = getDetail(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '商品市调详情接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '商品市调详情接口请求失败';
    detail.value = {};
  } finally {
    loading.value = false;
  }
}

onMounted(loadResearchDetail);
</script>

<style scoped>
.product-page {
  display: grid;
  gap: 16px;
}

.product-header {
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

.product-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
