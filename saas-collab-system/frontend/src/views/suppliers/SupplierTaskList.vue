<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">供应商任务列表</h1>
        <p>API: GET /api/external/supplier/tasks/</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert title="供应商只能查看和回填当前供应商自己的任务，真实过滤以后端 tenant_id + supplier_id 为准。" type="info" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

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

    <el-empty v-if="!loading && !message && rows.length === 0" description="暂无供应商任务" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchSupplierTasks } from '../../api/suppliers';

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
    const response = await fetchSupplierTasks();
    if (!response.success) throw new Error(response.message || '供应商任务接口失败');
    rows.value = getRows(response.data);
    status.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || '供应商任务请求失败';
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
