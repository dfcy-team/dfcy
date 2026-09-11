<template>
  <section aria-label="缺失同步任务预览" :aria-busy="loading">
    <el-button :loading="loading" :disabled="loading" @click="load">预览缺失任务（不创建）</el-button>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="result">
      <el-alert :title="result.notice" type="info" :closable="false" show-icon />
      <el-table :data="result.items" border empty-text="当前权限范围内没有缺失任务；已有停用任务不重复列出。">
        <el-table-column prop="subject_name" label="店铺 / 仓库" min-width="160" />
        <el-table-column prop="integration_config_id" label="接入配置 ID" width="120" />
        <el-table-column label="任务类型" min-width="150">
          <template #default="{ row }">{{ resourceLabels[row.resource_type] || row.resource_type }}</template>
        </el-table-column>
        <el-table-column label="状态" width="140">
          <template #default="{ row }">{{ row.status === 'blocked' ? '先补配置' : '任务缺失' }}</template>
        </el-table-column>
        <el-table-column label="缺失项 / 下一步" min-width="280">
          <template #default="{ row }">{{ row.blockers.join('；') || '前往主体 API 接入页面核对配置；本预览不会创建或启用任务。' }}</template>
        </el-table-column>
      </el-table>
    </template>
  </section>
</template>

<script setup>
import { ref } from 'vue';
import { requestApi } from '../api/request';

const loading = ref(false);
const error = ref('');
const result = ref(null);
const resourceLabels = { platform_product: '平台商品', sales_order: '销售订单', refund_return: '退货退款', inventory_snapshot: '库存快照' };
async function load() {
  if (loading.value) return;
  loading.value = true;
  error.value = '';
  result.value = null;
  try {
    const response = await requestApi({ method: 'get', url: '/api/internal/integrations/sync-jobs/missing-preview/' });
    if (!response.success) throw new Error(response.message || '预览失败，请重试。');
    result.value = response.data;
  } catch (failure) {
    error.value = failure.message || '预览失败，请重试。';
  } finally {
    loading.value = false;
  }
}
</script>
