<template>
  <section class="supplier-page">
    <header class="supplier-header">
      <div>
        <h1 class="page-title">供应商出货列表</h1>
        <p class="page-note">后续对接API路径：GET /api/external/supplier/shipments/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert title="仅展示当前供应商自己的出货记录；真实 supplier_id 过滤以后端为准，前端不做真实权限过滤。" type="info" show-icon :closable="false" />

    <el-form class="supplier-search" inline>
      <el-form-item label="出货单号"><el-input v-model="filters.shipment_no" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="SKU"><el-input v-model="filters.sku_code" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="状态"><el-input v-model="filters.status" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>图片附件占位</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无供应商出货记录">
      <el-table-column prop="shipment_no" label="出货单号" min-width="160" />
      <el-table-column prop="supplier_id" label="供应商ID" min-width="110" />
      <el-table-column prop="sku_code" label="SKU" min-width="140" />
      <el-table-column prop="ship_quantity" label="出货数量" min-width="110" />
      <el-table-column prop="carton_count" label="箱数" min-width="90" />
      <el-table-column prop="weight" label="重量" min-width="100" />
      <el-table-column prop="volume" label="体积" min-width="100" />
      <el-table-column prop="status" label="状态" min-width="110" />
    </el-table>

    <el-empty v-if="!loading && !errorMessage && rows.length === 0" description="暂无供应商出货记录" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchSupplierShipments } from '../../api/suppliers';

const filters = reactive({
  shipment_no: '',
  sku_code: '',
  status: ''
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

async function loadSupplierShipments() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchSupplierShipments();
    if (!response.success) throw new Error(response.message || '供应商出货接口返回失败');

    rows.value = getRows(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '供应商出货接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '供应商出货接口请求失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadSupplierShipments);
</script>

<style scoped>
.supplier-page {
  display: grid;
  gap: 16px;
}

.supplier-header {
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

.supplier-search {
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}
</style>
