<template>
  <section class="product-page">
    <header class="product-header">
      <div>
        <h1 class="page-title">商品主数据列表</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/products/spus/ 与 GET /api/internal/products/skus/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-form class="product-search" inline>
      <el-form-item label="SPU"><el-input v-model="filters.spu_code" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="商品名称"><el-input v-model="filters.product_name" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="销售状态"><el-input v-model="filters.sales_status" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>重置占位</el-button>
      </el-form-item>
    </el-form>

    <div class="product-actions">
      <el-button disabled>新增商品占位</el-button>
      <el-button disabled>导出占位</el-button>
    </div>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无商品主数据">
      <el-table-column prop="spu_code" label="SPU" min-width="150" />
      <el-table-column prop="sku_codes" label="SKU" min-width="170" show-overflow-tooltip />
      <el-table-column prop="product_name" label="商品名称" min-width="180" />
      <el-table-column prop="category" label="类目" min-width="130" />
      <el-table-column prop="lifecycle_status" label="生命周期状态" min-width="130" />
      <el-table-column prop="sales_status" label="销售状态" min-width="120" />
      <el-table-column label="是否归档" min-width="100">
        <template #default="{ row }">{{ row.lifecycle_status === 'discontinued' ? '是' : '否' }}</template>
      </el-table-column>
      <el-table-column prop="is_code_frozen" label="编码冻结" min-width="100">
        <template #default="{ row }">{{ row.is_code_frozen ? '已冻结' : '未冻结' }}</template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !errorMessage && rows.length === 0" description="暂无商品主数据" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchProductMasterList, fetchProductSkuList } from '../../api/products';

const filters = reactive({
  spu_code: '',
  product_name: '',
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

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function mergeSkuCodes(spus, skus) {
  return spus.map((spu) => {
    const skuCodes = skus.filter((sku) => sku.spu === spu.id).map((sku) => sku.sku_code);
    return {
      ...spu,
      sku_codes: skuCodes.join(', ') || '-'
    };
  });
}

async function loadProducts() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const [spuResponse, skuResponse] = await Promise.all([fetchProductMasterList(), fetchProductSkuList()]);
    if (!spuResponse.success) throw new Error(spuResponse.message || '商品主数据接口返回失败');
    if (!skuResponse.success) throw new Error(skuResponse.message || '商品SKU接口返回失败');

    rows.value = mergeSkuCodes(getRows(spuResponse.data), getRows(skuResponse.data));
    dataStatus.value = spuResponse.data?.api_status || spuResponse.data?.status || 'api';
    if (spuResponse.data?.api_status === 'fallback' || skuResponse.data?.api_status === 'fallback') {
      warningMessage.value = spuResponse.message || skuResponse.message || '商品主数据接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '商品主数据接口请求失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadProducts);
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
