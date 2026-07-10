<template><Phase2DataPage title="RPA账号锁" note="GET /api/internal/rpa/account-locks/" :loader="fetchRpaAccountLocks" :columns="columns" empty-text="暂无账号锁" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaAccountLocks } from '../../api/rpaStability';
const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'account_alias', label: '账号别名' }, { prop: 'task', label: '任务' },
  { prop: 'lock_status', label: '锁状态', type: 'status' }, { prop: 'acquired_at', label: '获取时间' }, { prop: 'expires_at', label: '过期时间' }, { prop: 'released_at', label: '释放时间' }
];
</script>
