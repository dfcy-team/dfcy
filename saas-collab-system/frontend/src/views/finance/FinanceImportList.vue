<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/finance/imports/
const rows = [
  { id: 'FIN-001', name: '财务导入记录', status: '待处理', owner: '财务', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="财务导入列表" :rows="rows" />
</template>
