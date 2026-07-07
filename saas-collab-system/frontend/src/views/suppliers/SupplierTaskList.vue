<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/suppliers/tasks/
const rows = [
  { id: 'ST-001', name: '供应商协同任务', status: '处理中', owner: '供应商', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="供应商任务列表" :rows="rows" />
</template>
