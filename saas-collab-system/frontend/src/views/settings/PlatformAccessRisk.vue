<template>
  <Phase2DataPage
    title="真实平台接入风险提示"
    note="只读风险占位页，不提供真实凭据输入、OAuth 跳转或生产连接按钮。"
    risk-note="真实平台接入必须完成专项安全评审。阶段2开发不代表允许启用生产平台。"
    :loader="mockPlatformAccessRisks"
    :columns="columns"
    :filters="['平台', '接入状态', '生产状态']"
    :actions="['专项安全评审入口占位', '生产连接禁用']"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { mockPlatformAccessRisks } from '../../mock/platformRisk';

const columns = [
  { prop: 'platform', label: '平台' },
  { prop: 'access_status', label: '当前接入状态', type: 'status', width: 160 },
  { prop: 'environment_status', label: 'Mock/Sandbox状态', type: 'status', width: 170 },
  { prop: 'production_status', label: '生产状态', type: 'status', width: 170 },
  { prop: 'security_review_done', label: '专项安全评审' },
  { prop: 'credential_custody_done', label: '密钥托管方案' },
  { prop: 'high_risk_action_allowed', label: '允许高风险动作' },
  { prop: 'risk_note', label: '风险提示', width: 220 },
  { prop: 'forbidden_items', label: '禁止事项', width: 260 }
];
</script>
