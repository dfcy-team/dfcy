<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/integrations/sync-tasks/
const rows = [
  { id: 'SYNC-001', name: 'API同步任务', status: '待同步', owner: '集成', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="API同步任务列表" :rows="rows" />
</template>
