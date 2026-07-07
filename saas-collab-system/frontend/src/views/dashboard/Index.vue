<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/dashboard/
const rows = [
  { id: 'DASH-001', name: '首页概览', status: 'Mock', owner: '系统', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="首页" :rows="rows" />
</template>
