<template>
  <Phase2DataPage
    title="同步执行详情"
    note="GET /api/internal/integrations/sync-runs/{id}/"
    mode="detail"
    :loader="() => fetchSyncRunDetail(route.params.id || 1)"
    :detail-fields="fields"
    empty-text="暂无执行详情"
  />
</template>

<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchSyncRunDetail } from '../../api/integrations';

const route = useRoute();
const fields = [
  { prop: 'run_id', label: '执行ID' },
  { prop: 'platform', label: '平台' },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'fetched_count', label: '抓取数' },
  { prop: 'created_count', label: '新增数' },
  { prop: 'updated_count', label: '更新数' },
  { prop: 'skipped_count', label: '跳过数' },
  { prop: 'failed_count', label: '失败数' },
  { prop: 'retry_count', label: '重试次数' },
  { prop: 'error_code', label: '错误码' },
  { prop: 'masked_error_message', label: '脱敏错误' },
  { prop: 'quality_check_result', label: '质量检查', type: 'json' }
];
</script>
