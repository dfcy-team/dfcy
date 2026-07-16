<template>
  <RPAResourcePage
    title="RPA页面签名"
    note="GET /api/internal/rpa/page-signatures/"
    boundary-note="页面变化只会暂停任务并转人工；前端不能自动恢复、改价、刊登或触发真实RPA。"
    :loader="fetchRpaPageSignatures"
    :columns="columns"
    empty-text="暂无页面签名记录"
  />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { fetchRpaPageSignatures } from '../../api/rpaStability';

const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'page_type', label: '页面类型' },
  { prop: 'signature_hash_masked', label: '签名Hash（脱敏）', width: 180 },
  { prop: 'detected_status', label: '检测状态', type: 'status' }, { prop: 'created_at', label: '检测时间', width: 180 }
];
</script>
