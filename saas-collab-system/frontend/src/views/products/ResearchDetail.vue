<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/products/research/{id}/
const rows = [
  { id: 'RS-001', name: '新品市调详情', status: 'Mock', owner: '产品', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="新品市调详情" :rows="rows" />
</template>
