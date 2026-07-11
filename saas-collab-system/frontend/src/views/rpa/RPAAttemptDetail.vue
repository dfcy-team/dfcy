<template><Phase2DataPage title="RPA尝试详情" note="GET /api/internal/rpa/attempts/{id}/" mode="detail" :loader="() => fetchRpaAttemptDetail(route.params.id || 1)" :detail-fields="fields" :actions="['人工接管确认占位','retry-mock 占位']" empty-text="暂无尝试详情" /></template>
<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaAttemptDetail } from '../../api/rpaStability';
const route = useRoute();
const fields = [
  { prop: 'task', label: '任务' }, { prop: 'attempt_no', label: '次数' }, { prop: 'agent', label: 'Agent' },
  { prop: 'started_at', label: '开始' }, { prop: 'heartbeat_at', label: '心跳' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'failed_step', label: '失败步骤' }, { prop: 'last_success_step', label: '最后成功步骤' }, { prop: 'masked_error', label: '脱敏错误' },
  { prop: 'evidence_type', label: '证据类型' }, { prop: 'placeholder_url', label: '占位证据' }, { prop: 'payload_hash', label: 'Payload Hash' }
];
</script>
