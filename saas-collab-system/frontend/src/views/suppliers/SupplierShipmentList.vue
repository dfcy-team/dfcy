<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/suppliers/shipments/
const rows = [
  { id: 'SS-001', name: '供应商发货单', status: '待发货', owner: '供应商', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="供应商发货列表" :rows="rows" />
</template>
