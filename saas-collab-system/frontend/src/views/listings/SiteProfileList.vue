<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/listings/site-profiles/
const rows = [
  { id: 'SITE-001', name: '站点资料', status: '启用', owner: '刊登', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="站点资料列表" :rows="rows" />
</template>
