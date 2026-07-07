<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/suppliers/shipments/{id}/
const rows = [
  { id: 'SS-001', name: '供应商发货详情', status: 'Mock', owner: '供应商', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="供应商发货详情" :rows="rows" />
</template>
