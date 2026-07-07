<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/pricing/prices/{id}/
const rows = [
  { id: 'PRICE-001', name: '价格详情', status: 'Mock', owner: '价格', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="价格详情" :rows="rows" />
</template>
