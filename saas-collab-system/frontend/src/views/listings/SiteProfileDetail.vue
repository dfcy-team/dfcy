<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/listings/site-profiles/{id}/
const rows = [
  { id: 'SITE-001', name: '站点资料详情', status: 'Mock', owner: '刊登', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="站点资料详情" :rows="rows" />
</template>
