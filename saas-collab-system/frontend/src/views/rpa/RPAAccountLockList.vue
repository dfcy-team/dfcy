<template>
  <RPAResourcePage
    title="RPA账号串行锁"
    note="GET /api/internal/rpa/account-locks/"
    boundary-note="同一 tenant、平台和账号只允许一个持有锁；管理页不能绕过或释放 Agent 锁。"
    :loader="fetchRpaAccountLocks"
    :columns="columns"
    empty-text="暂无账号锁"
  />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { fetchRpaAccountLocks } from '../../api/rpaStability';

const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'account_alias', label: '账号别名' },
  { prop: 'task_id', label: '任务ID' }, { prop: 'lock_status', label: '锁状态', type: 'status' },
  { prop: 'acquired_at', label: '获取时间', width: 180 }, { prop: 'expires_at', label: '过期时间', width: 180 },
  { prop: 'released_at', label: '释放时间', width: 180 }
];
</script>
