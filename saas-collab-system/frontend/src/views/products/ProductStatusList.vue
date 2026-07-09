<template>
  <section class="product-page">
    <header class="product-header">
      <div>
        <h1 class="page-title">商品销售状态</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/products/spus/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-form class="product-search" inline>
      <el-form-item label="SPU"><el-input v-model="filters.spu_code" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="生命周期状态"><el-input v-model="filters.lifecycle_status" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="销售状态"><el-input v-model="filters.sales_status" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>导出占位</el-button>
      </el-form-item>
    </el-form>

    <div class="status-summary">
      <el-tag v-for="item in statusSummary" :key="item.label" :type="item.type">
        {{ item.label }}：{{ item.count }}
      </el-tag>
    </div>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无商品状态数据">
      <el-table-column prop="spu_code" label="SPU" min-width="150" />
      <el-table-column prop="product_name" label="商品名称" min-width="180" />
      <el-table-column prop="category" label="类目" min-width="130" />
      <el-table-column prop="lifecycle_status" label="生命周期状态" min-width="140" />
      <el-table-column prop="sales_status" label="销售状态" min-width="120" />
      <el-table-column label="编码冻结" min-width="100">
        <template #default="{ row }">{{ row.is_code_frozen ? '已冻结' : '未冻结' }}</template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !errorMessage && rows.length === 0" description="暂无商品状态数据" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchProductStatusList } from '../../api/products';

const filters = reactive({
  spu_code: '',
  lifecycle_status: '',
  sales_status: ''
});
const rows = ref([]);
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

const statusSummary = computed(() => [
  { label: '新品', count: rows.value.filter((item) => item.lifecycle_status === 'draft').length, type: 'info' },
  { label: '正常', count: rows.value.filter((item) => item.sales_status === 'on_sale').length, type: 'success' },
  { label: '爆品', count: 0, type: 'success' },
  { label: '滞销', count: 0, type: 'warning' },
  { label: '清仓中', count: rows.value.filter((item) => item.sales_status === 'paused').length, type: 'warning' },
  { label: '已清仓', count: rows.value.filter((item) => item.lifecycle_status === 'discontinued').length, type: 'danger' },
  { label: '已下架', count: rows.value.filter((item) => item.sales_status === 'stopped').length, type: 'danger' }
]);

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

async function loadProductStatus() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchProductStatusList();
    if (!response.success) {
      throw new Error(response.message || '商品状态接口返回失败');
    }

    rows.value = getRows(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '商品状态接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '商品状态接口请求失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadProductStatus);
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

.product-search {
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}

.status-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
