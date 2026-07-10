<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">采购订单列表</h1>
        <p>API: GET /api/internal/purchasing/orders/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-form class="fix-search" inline>
      <el-form-item label="采购单号"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item label="SKU"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item label="状态"><el-input placeholder="搜索占位" disabled /></el-form-item>
      <el-form-item><el-button disabled>搜索占位</el-button></el-form-item>
    </el-form>

    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无采购订单">
      <el-table-column prop="po_no" label="采购单号" min-width="150" />
      <el-table-column prop="sku_code" label="SKU" min-width="140" />
      <el-table-column prop="supplier_id" label="供应商ID" min-width="110" />
      <el-table-column prop="quantity" label="采购数量" min-width="110" />
      <el-table-column prop="unit_price" label="单价" min-width="100" />
      <el-table-column prop="delivery_date" label="交期" min-width="130" />
      <el-table-column prop="status" label="状态" min-width="120" />
      <el-table-column prop="approval_status" label="审批状态" min-width="120" />
    </el-table>

    <el-empty v-if="!loading && !message && rows.length === 0" description="暂无采购订单" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchPurchaseOrders } from '../../api/purchasing';

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

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchPurchaseOrders();
    if (!response.success) throw new Error(response.message || '采购订单接口失败');
    rows.value = getRows(response.data);
    status.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '采购订单请求失败';
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
