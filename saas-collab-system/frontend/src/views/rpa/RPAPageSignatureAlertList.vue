<template><Phase2DataPage title="RPA页面签名异常" note="GET /api/internal/rpa/page-signatures/" risk-note="页面签名异常只能显示暂停或人工检查建议，不允许前端自动恢复高风险任务。" :loader="fetchRpaPageSignatures" :columns="columns" empty-text="暂无页面签名异常" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaPageSignatures } from '../../api/rpaStability';
const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'page_type', label: '页面类型' }, { prop: 'signature_hash', label: '签名Hash' },
  { prop: 'detected_status', label: '检测状态', type: 'status' }, { prop: 'created_at', label: '创建时间' }
];
</script>
