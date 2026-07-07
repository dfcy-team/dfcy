<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/rpa/tasks/
const rows = [
  { id: 'RPA-001', name: 'RPA任务', status: '排队中', owner: '自动化', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="RPA任务列表" :rows="rows" />
</template>
