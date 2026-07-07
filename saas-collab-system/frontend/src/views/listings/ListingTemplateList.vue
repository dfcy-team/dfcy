<script setup>
import MvpPage from '../../components/MvpPage.vue'

// 后续对接API路径：GET /api/internal/listings/templates/
const rows = [
  { id: 'TPL-001', name: '刊登模板', status: '草稿', owner: '刊登', updated_at: '2026-07-07' },
]
</script>

<template>
  <MvpPage title="刊登模板列表" :rows="rows" />
</template>
