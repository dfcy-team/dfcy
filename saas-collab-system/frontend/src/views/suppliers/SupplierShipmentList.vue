<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">供应商出货列表</h1>
        <p>API: GET /api/external/supplier/shipments/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert title="供应商只能查看和回填当前供应商自己的任务，真实过滤以后端 tenant_id + supplier_id 为准。" type="info" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无出货记录">
      <el-table-column prop="shipment_no" label="出货单号" min-width="160" />
      <el-table-column prop="supplier_id" label="供应商ID" min-width="110" />
      <el-table-column prop="sku_code" label="SKU" min-width="140" />
      <el-table-column prop="ship_quantity" label="出货数量" min-width="110" />
      <el-table-column prop="carton_count" label="箱数" min-width="90" />
      <el-table-column prop="weight" label="重量" min-width="100" />
      <el-table-column prop="volume" label="体积" min-width="100" />
      <el-table-column prop="status" label="状态" min-width="110" />
    </el-table>

    <el-empty v-if="!loading && !message && rows.length === 0" description="暂无出货记录" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchSupplierShipments } from '../../api/suppliers';

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
    const response = await fetchSupplierShipments();
    if (!response.success) throw new Error(response.message || '供应商出货接口失败');
    rows.value = getRows(response.data);
    status.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '供应商出货请求失败';
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
