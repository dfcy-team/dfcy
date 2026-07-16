<template>
  <RPAResourcePage
    title="RPA设备"
    note="GET /api/internal/rpa/devices/"
    boundary-note="只有 Mock/dry-run 设备可执行本地检查；production_disabled 设备始终拒绝执行。"
    :loader="fetchRpaDevices"
    :columns="columns"
    :row-actions="actions"
    empty-text="暂无RPA设备"
  />
</template>

<script setup>
import { useRouter } from 'vue-router';
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { fetchRpaDevices, runRpaDeviceDryRun } from '../../api/rpaStability';

const router = useRouter();
const columns = [
  { prop: 'name', label: '设备名称' }, { prop: 'status', label: '注册状态', type: 'status' },
  { prop: 'execution_mode', label: '执行模式', type: 'status' }, { prop: 'availability', label: '在线状态', type: 'status' },
  { prop: 'fingerprint_masked', label: '设备指纹（脱敏）', width: 180 }, { prop: 'last_heartbeat_at', label: '最近心跳', width: 180 }
];
const actions = [
  { label: '详情', permission: 'rpa.devices.view', handler: (row) => router.push(`/rpa/devices/${row.id}`) },
  {
    label: 'dry-run', type: 'warning', permission: 'rpa.devices.dry_run',
    disabled: (row) => !['mock', 'dry_run'].includes(row.execution_mode) || row.status !== 'active',
    confirmMessage: '只执行本地绑定与配置检查，不启动浏览器、不连接平台。',
    handler: (row) => runRpaDeviceDryRun(row.id)
  }
];
</script>
