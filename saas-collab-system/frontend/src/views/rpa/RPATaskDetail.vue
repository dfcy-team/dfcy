<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/rpa/tasks/{id}/
const rows = [
  { id: 'RPA-001', name: 'RPA任务详情', status: 'Mock', owner: '自动化', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="RPA任务详情" :rows="rows" />
</template>
