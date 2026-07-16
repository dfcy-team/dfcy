<template>
  <Phase3DecisionPage
    eyebrow="商品决策"
    title="生命周期复盘"
    subtitle="查看阶段建议、规则证据与人工复核状态。"
    boundary-note="页面只展示状态建议；清仓、停售和归档必须人工确认，且不会在此处改价、下架或改变商品状态。"
    :loader="fetchLifecycleReviews"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="待复盘商品"
    table-note="高置信度不等于自动执行，仍需后端授权与人工判断"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { confirmLifecycleReview, fetchLifecycleReviews, rejectLifecycleReview } from '../../api/lifecycle';

const filters = [
  { key: 'suggested_stage', label: '建议阶段', options: [{ label: '滞销观察期', value: 'slow_observation' }, { label: '清仓候选', value: 'clearance_candidate' }, { label: '停售', value: 'stopped' }, { label: '归档', value: 'archived' }] },
  { key: 'period', label: '复盘周期', options: [{ label: '周', value: 'week' }, { label: '月', value: 'month' }] }
];
const columns = [
  { prop: 'id', label: '复盘编号', width: 150 }, { prop: 'spu', label: 'SPU', width: 140 },
  { prop: 'current_stage', label: '当前阶段', width: 130 }, { prop: 'suggested_stage', label: '建议阶段', width: 130 },
  { prop: 'confidence', label: '置信度', type: 'confidence', width: 150 }, { prop: 'rule_version', label: '规则版本', width: 130 }, { prop: 'status', label: '状态', type: 'status' }
];
const rowActions = [
  { label: '查看证据', mode: 'detail' },
  { label: '人工确认建议', permission: 'products.lifecycle.confirm', confirmMessage: '后端会校验授权和高风险权限；该操作只记录生命周期决策，不会直接改价、下架或改变商品状态。', execute: (row) => confirmLifecycleReview(row.id, { reason: 'Human lifecycle review confirmed.' }) },
  { label: '人工拒绝建议', permission: 'products.lifecycle.confirm', type: 'danger', confirmMessage: '该操作仅记录人工决策，不会触发任何商品自动化动作。', execute: (row) => rejectLifecycleReview(row.id, { reason: 'Human lifecycle review rejected.' }) }
];
const detailFields = [
  { prop: 'id', label: '复盘编号' }, { prop: 'reason_detail', label: '建议原因' }, { prop: 'review_period_start', label: '复盘开始' },
  { prop: 'review_period_end', label: '复盘结束' }, { prop: 'source_metrics', label: '分析证据', type: 'json' }
];
</script>
