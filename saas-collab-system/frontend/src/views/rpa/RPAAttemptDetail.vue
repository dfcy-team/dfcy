<template>
  <Phase2DataPage
    title="RPA运行详情"
    note="GET /api/internal/rpa/runs/{id}/"
    risk-note="本页只展示运行证据，不调用 Agent 执行端点。"
    mode="detail"
    :loader="() => fetchRpaRunDetail(route.params.id || 1)"
    :detail-fields="fields"
    empty-text="暂无运行详情"
  />
</template>

<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaRunDetail } from '../../api/rpaStability';

const route = useRoute();
const fields = [
  { prop: 'task_code', label: '任务编号' }, { prop: 'attempt_no', label: '运行次数' },
  { prop: 'agent', label: '设备' }, { prop: 'status', label: '运行状态', type: 'status' },
  { prop: 'started_at', label: '开始时间' }, { prop: 'heartbeat_at', label: '最近心跳' },
  { prop: 'finished_at', label: '结束时间' }, { prop: 'failed_step', label: '失败步骤' },
  { prop: 'last_success_step', label: '最后成功步骤' }, { prop: 'masked_error', label: '脱敏错误' },
  { prop: 'manual_required', label: '需要人工' }
];
</script>
