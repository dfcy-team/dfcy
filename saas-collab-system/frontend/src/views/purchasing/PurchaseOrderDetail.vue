<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/purchasing/orders/{id}/
const rows = [
  { id: 'PO-001', name: '采购订单详情', status: 'Mock', owner: '采购', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="采购订单详情" :rows="rows" />
</template>
