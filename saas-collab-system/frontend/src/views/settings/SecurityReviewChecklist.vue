<template>
  <Phase2DataPage
    title="专项安全评审清单"
    note="真实 BigSeller、Shopee、TikTok/TK、银行和支付接入前的只读检查清单。"
    risk-note="未完成专项安全评审前，不允许输入真实 Token、Cookie、Session、API Key、API Secret 或账号密码。"
    :loader="mockSecurityReviewChecklist"
    :columns="columns"
    :filters="['检查项', '状态', '责任人']"
    :actions="['提交评审占位', '查看证据占位']"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { mockSecurityReviewChecklist } from '../../mock/platformRisk';

const columns = [
  { prop: 'item', label: '检查项', width: 220 },
  { prop: 'status', label: '状态', type: 'status', width: 180 },
  { prop: 'owner', label: '后续负责人', width: 180 },
  { prop: 'required_for', label: '适用范围', width: 180 },
  { prop: 'evidence_status', label: '证据状态', type: 'status', width: 150 },
  { prop: 'note', label: '说明', width: 260 }
];
</script>
