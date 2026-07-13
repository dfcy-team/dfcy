<template>
  <Phase3DecisionPage
    eyebrow="商品决策"
    title="生命周期复盘历史"
    subtitle="追踪复盘建议、人工结论和审计证据。"
    boundary-note="历史记录仅用于审计展示，不提供商品状态回滚或自动执行入口。"
    :loader="fetchLifecycleDecisions"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="复盘记录"
    table-note="记录建议、结论、原因、规则版本与操作时间"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { fetchLifecycleDecisions } from '../../api/lifecycle';

const filters = [
  { key: 'decision', label: '结论', options: [{ label: '已确认', value: 'confirmed' }, { label: '已拒绝', value: 'rejected' }] },
  { key: 'rule_version', label: '规则版本', options: [{ label: 'demo-life-v3', value: 'demo-life-v3' }] }
];
const columns = [
  { prop: 'history_id', label: '记录编号', width: 150 }, { prop: 'spu_code', label: 'SPU', width: 140 },
  { prop: 'from_stage', label: '原阶段', width: 130 }, { prop: 'suggested_stage', label: '建议阶段', width: 130 },
  { prop: 'decision', label: '人工结论', type: 'status' }, { prop: 'reviewer', label: '复盘人', width: 130 },
  { prop: 'rule_version', label: '规则版本', width: 130 }, { prop: 'reviewed_at', label: '复盘时间', width: 160 }
];
const rowActions = [{ label: '审计证据', mode: 'detail' }];
const detailFields = [
  { prop: 'history_id', label: '记录编号' }, { prop: 'reason', label: '处理原因' }, { prop: 'audit_evidence', label: '审计证据', type: 'json' }
];
</script>
