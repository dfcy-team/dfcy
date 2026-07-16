<template>
  <Phase2DataPage
    title="RPA设备详情"
    note="GET /api/internal/rpa/devices/{id}/"
    risk-note="Token、IP白名单和完整指纹不返回前端；production 模式保持禁用。"
    mode="detail"
    :loader="() => fetchRpaDeviceDetail(route.params.id || 1)"
    :detail-fields="fields"
    empty-text="暂无设备详情"
  />
</template>

<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaDeviceDetail } from '../../api/rpaStability';

const route = useRoute();
const fields = [
  { prop: 'name', label: '设备名称' }, { prop: 'status', label: '注册状态', type: 'status' },
  { prop: 'execution_mode', label: '执行模式', type: 'status' }, { prop: 'availability', label: '在线状态', type: 'status' },
  { prop: 'fingerprint_masked', label: '设备指纹（脱敏）' }, { prop: 'last_heartbeat_at', label: '最近心跳' }
];
</script>
