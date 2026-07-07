<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/integrations/sync-logs/
const rows = [
  { id: 'LOG-001', name: 'API同步日志', status: '成功', owner: '集成', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="API同步日志列表" :rows="rows" />
</template>
