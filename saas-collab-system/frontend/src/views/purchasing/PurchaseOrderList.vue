<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/purchasing/orders/
const rows = [
  { id: 'PO-001', name: '采购订单', status: '待确认', owner: '采购', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="采购订单列表" :rows="rows" />
</template>
