<template>
  <section class="ops-page">
    <header class="ops-header">
      <div>
        <h1 class="page-title">采购订单列表</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/purchasing/orders/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-form class="ops-search" inline>
      <el-form-item label="采购单号"><el-input v-model="filters.po_no" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="SKU"><el-input v-model="filters.sku_code" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="状态"><el-input v-model="filters.status" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>重置占位</el-button>
      </el-form-item>
    </el-form>

    <div class="ops-actions">
      <el-button disabled>新增采购单占位</el-button>
      <el-button disabled>提交审批占位</el-button>
    </div>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

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

    <el-empty v-if="!loading && !errorMessage && rows.length === 0" description="暂无采购订单" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchPurchaseOrders } from '../../api/purchasing';

const filters = reactive({
  po_no: '',
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

async function loadPurchaseOrders() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchPurchaseOrders();
    if (!response.success) throw new Error(response.message || '采购订单接口返回失败');

    rows.value = getRows(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '采购订单接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '采购订单接口请求失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadPurchaseOrders);
</script>

<style scoped>
.ops-page {
  display: grid;
  gap: 16px;
}

.ops-header {
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

.ops-search {
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}

.ops-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
