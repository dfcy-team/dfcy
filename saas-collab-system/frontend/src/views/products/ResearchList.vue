<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">新品市调列表</h1>
        <p>API: GET /api/internal/products/research/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-form class="fix-search" inline>
      <el-form-item label="市调编号"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item label="商品名称"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item label="平台"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item><el-button disabled>搜索占位</el-button></el-form-item>
    </el-form>

    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无市调数据">
      <el-table-column prop="research_no" label="市调编号" min-width="150" />
      <el-table-column prop="product_name" label="商品名称" min-width="160" />
      <el-table-column prop="platform" label="平台" min-width="120" />
      <el-table-column prop="competitor_url" label="竞品链接" min-width="220" show-overflow-tooltip />
      <el-table-column prop="estimated_sales" label="预估销量" min-width="110" />
      <el-table-column prop="estimated_gross_margin" label="预估毛利" min-width="110" />
      <el-table-column label="风险点" min-width="160">
        <template #default="{ row }">{{ formatList(row.risk_points) }}</template>
      </el-table-column>
      <el-table-column prop="approval_status" label="状态" min-width="110" />
    </el-table>

    <el-empty v-if="!loading && !message && rows.length === 0" description="暂无市调数据" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchResearchList } from '../../api/products';

const rows = ref([]);
const loading = ref(false);
const status = ref('loading');
const message = ref('');

const tagType = computed(() => {
  if (status.value === 'error') return 'danger';
  if (status.value === 'fallback') return 'warning';
  if (status.value === 'mock' || status.value === 'pending') return 'info';
  return 'success';
});

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function formatList(value) {
  return Array.isArray(value) ? value.join(', ') : value || '-';
}

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchResearchList();
    if (!response.success) throw new Error(response.message || '新品市调接口失败');
    rows.value = getRows(response.data);
    status.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '新品市调请求失败';
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.fix-search { padding: 12px; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
</style>
