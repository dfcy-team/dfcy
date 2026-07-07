<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/reports/basic/
const rows = [
  { id: 'RPT-001', name: '基础报表', status: 'Mock', owner: 'BI', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="BI基础报表" :rows="rows" />
</template>
