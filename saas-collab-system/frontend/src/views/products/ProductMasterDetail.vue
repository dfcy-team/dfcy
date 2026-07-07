<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/products/master/{id}/
const rows = [
  { id: 'SKU-001', name: '商品主数据详情', status: 'Mock', owner: '产品', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="商品主数据详情" :rows="rows" />
</template>
