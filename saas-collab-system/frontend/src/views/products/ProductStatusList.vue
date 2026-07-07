<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/products/status/
const rows = [
  { id: 'PST-001', name: '商品状态记录', status: '启用', owner: '产品', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="商品状态列表" :rows="rows" />
</template>
