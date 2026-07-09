<template>
  <section class="supplier-page">
    <header class="supplier-header">
      <div>
        <h1 class="page-title">供应商任务列表</h1>
        <p class="page-note">后续对接API路径：GET /api/external/supplier/tasks/</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert title="仅展示当前供应商自己的任务；真实 supplier_id 过滤以后端为准，前端不做真实权限过滤。" type="info" show-icon :closable="false" />

    <el-form class="supplier-search" inline>
      <el-form-item label="任务编号"><el-input v-model="filters.task_no" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="SKU"><el-input v-model="filters.sku_code" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="状态"><el-input v-model="filters.status" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>回填记录占位</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无供应商任务">
      <el-table-column prop="task_no" label="任务编号" min-width="170" />
      <el-table-column prop="supplier_id" label="供应商ID" min-width="110" />
      <el-table-column prop="sku_code" label="SKU" min-width="140" />
      <el-table-column prop="production_quantity" label="生产数量" min-width="110" />
      <el-table-column prop="completed_quantity" label="已完成数量" min-width="120" />
      <el-table-column prop="expected_ship_date" label="预计出货日期" min-width="140" />
      <el-table-column prop="status" label="状态" min-width="120" />
      <el-table-column label="是否逾期" min-width="100">
        <template #default="{ row }">{{ row.is_overdue ? '是' : '否' }}</template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !errorMessage && rows.length === 0" description="暂无供应商任务" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchSupplierTasks } from '../../api/suppliers';

const filters = reactive({
  task_no: '',
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

async function loadSupplierTasks() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchSupplierTasks();
    if (!response.success) throw new Error(response.message || '供应商任务接口返回失败');

    rows.value = getRows(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || '供应商任务接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || '供应商任务接口请求失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadSupplierTasks);
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
