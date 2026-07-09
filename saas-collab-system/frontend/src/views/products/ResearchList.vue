<template>
  <section class="product-page">
    <header class="product-header">
      <div>
        <h1 class="page-title">新品市调列表</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/products/research/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-form class="product-search" inline>
      <el-form-item label="市调编号"><el-input v-model="filters.research_no" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="商品名称"><el-input v-model="filters.product_name" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="平台"><el-input v-model="filters.platform" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>重置占位</el-button>
      </el-form-item>
    </el-form>

    <div class="product-actions">
      <el-button disabled>新增市调占位</el-button>
      <el-button disabled>附件上传占位</el-button>
      <el-button disabled>提交审批占位</el-button>
    </div>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无商品市调数据">
      <el-table-column prop="research_no" label="市调编号" min-width="150" />
      <el-table-column prop="product_name" label="商品名称" min-width="160" />
      <el-table-column prop="platform" label="平台" min-width="120" />
      <el-table-column prop="competitor_url" label="竞品链接" min-width="220" show-overflow-tooltip />
      <el-table-column prop="estimated_sales" label="预估销量" min-width="110" />
      <el-table-column prop="estimated_gross_margin" label="预估毛利" min-width="110" />
      <el-table-column prop="approval_status" label="状态" min-width="110" />
      <el-table-column prop="created_by_id" label="创建人" min-width="100" />
      <el-table-column prop="created_at" label="创建时间" min-width="180" />
    </el-table>

    <el-empty v-if="!loading && !errorMessage && rows.length === 0" description="暂无商品市调数据" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchResearchList } from '../../api/products';

const filters = reactive({
  research_no: '',
  product_name: '',
  platform: ''
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

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

async function loadResearchList() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchResearchList();
    if (!response.success) {
      throw new Error(response.message || '商品市调接口返回失败');
    }

    rows.value = getRows(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '商品市调接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '商品市调接口请求失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadResearchList);
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

.product-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
