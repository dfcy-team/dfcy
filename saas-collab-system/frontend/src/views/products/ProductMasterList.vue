<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">商品主数据列表</h1>
        <p>API: GET /api/internal/products/spus/ + /api/internal/products/skus/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-form class="fix-search" inline>
      <el-form-item label="SPU"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item label="SKU"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item label="销售状态"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item><el-button disabled>搜索占位</el-button></el-form-item>
    </el-form>

    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无商品主数据">
      <el-table-column prop="spu_code" label="SPU" min-width="150" />
      <el-table-column prop="sku_codes" label="SKU" min-width="180" show-overflow-tooltip />
      <el-table-column prop="product_name" label="商品名称" min-width="160" />
      <el-table-column prop="category" label="类目" min-width="120" />
      <el-table-column prop="lifecycle_status" label="生命周期状态" min-width="130" />
      <el-table-column prop="sales_status" label="销售状态" min-width="120" />
      <el-table-column label="是否冻结" min-width="100">
        <template #default="{ row }">{{ row.is_code_frozen ? '是' : '否' }}</template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !message && rows.length === 0" description="暂无商品主数据" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchProductMasterList, fetchProductSkuList } from '../../api/products';

const rows = ref([]);
const loading = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function mergeRows(spus, skus) {
  return spus.map((spu) => ({
    ...spu,
    sku_codes: skus.filter((sku) => sku.spu === spu.id).map((sku) => sku.sku_code).join(', ') || '-'
  }));
}

onMounted(async () => {
  loading.value = true;
  try {
    const [spuResponse, skuResponse] = await Promise.all([fetchProductMasterList(), fetchProductSkuList()]);
    if (!spuResponse.success) throw new Error(spuResponse.message || 'SPU接口失败');
    if (!skuResponse.success) throw new Error(skuResponse.message || 'SKU接口失败');
    rows.value = mergeRows(getRows(spuResponse.data), getRows(skuResponse.data));
    status.value = spuResponse.data?.api_status || spuResponse.data?.status || 'api';
    if (spuResponse.data?.api_status === 'fallback' || skuResponse.data?.api_status === 'fallback') {
      message.value = spuResponse.message || skuResponse.message;
      status.value = 'fallback';
    }
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '商品主数据请求失败';
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
