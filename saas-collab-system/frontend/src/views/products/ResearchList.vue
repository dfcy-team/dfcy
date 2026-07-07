<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/products/research/
const rows = [
  { id: 'RS-001', name: '新品市调任务', status: '待评估', owner: '产品', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="新品市调列表" :rows="rows" />
</template>
