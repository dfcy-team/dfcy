<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">商品销售状态</h1>
        <p>API: GET /api/internal/products/spus/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <div class="status-tags">
      <el-tag v-for="item in summary" :key="item.label" :type="item.type">{{ item.label }}：{{ item.count }}</el-tag>
    </div>

    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无商品状态数据">
      <el-table-column prop="spu_code" label="SPU" min-width="150" />
      <el-table-column prop="product_name" label="商品名称" min-width="160" />
      <el-table-column prop="category" label="类目" min-width="120" />
      <el-table-column prop="lifecycle_status" label="生命周期状态" min-width="130" />
      <el-table-column prop="sales_status" label="销售状态" min-width="120" />
      <el-table-column label="编码冻结" min-width="100">
        <template #default="{ row }">{{ row.is_code_frozen ? '是' : '否' }}</template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !message && rows.length === 0" description="暂无商品状态数据" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchProductStatusList } from '../../api/products';
import { apiState, collectionRows } from '../../utils/businessResponse';

const rows = ref([]);
const loading = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));
const summary = computed(() => [
  { label: '新品', count: rows.value.filter((item) => item.lifecycle_status === 'draft').length, type: 'info' },
  { label: '正常', count: rows.value.filter((item) => item.sales_status === 'on_sale').length, type: 'success' },
  { label: '清仓中', count: rows.value.filter((item) => item.sales_status === 'paused').length, type: 'warning' },
  { label: '已下架', count: rows.value.filter((item) => item.sales_status === 'stopped').length, type: 'danger' }
]);

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchProductStatusList();
    if (!response.success) throw new Error(response.message || '商品状态接口失败');
    rows.value = collectionRows(response.data);
    status.value = apiState(response.data);
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '商品状态请求失败';
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.status-tags { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
