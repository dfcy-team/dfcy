<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/audit/operation-logs/
const rows = [
  { id: 'AUD-001', name: '操作日志', status: '已记录', owner: '系统', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="操作日志列表" :rows="rows" />
</template>
