<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/pricing/prices/
const rows = [
  { id: 'PRICE-001', name: '价格记录', status: '待生效', owner: '价格', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="价格列表" :rows="rows" />
</template>
