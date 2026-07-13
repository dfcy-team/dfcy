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
import { fetchLifecycleReviews } from '../../api/lifecycle';

const filters = [
  { key: 'suggested_stage', label: '建议阶段', options: [{ label: '滞销观察期', value: 'slow_observation' }, { label: '清仓候选', value: 'clearance_candidate' }, { label: '停售', value: 'stopped' }, { label: '归档', value: 'archived' }] },
  { key: 'period', label: '复盘周期', options: [{ label: '周', value: 'week' }, { label: '月', value: 'month' }] }
];
const columns = [
  { prop: 'review_id', label: '复盘编号', width: 150 }, { prop: 'spu_code', label: 'SPU', width: 140 }, { prop: 'product_name', label: '商品', width: 160 },
  { prop: 'current_stage', label: '当前阶段', width: 130 }, { prop: 'suggested_stage', label: '建议阶段', width: 130 },
  { prop: 'confidence', label: '置信度', type: 'confidence', width: 150 }, { prop: 'rule_version', label: '规则版本', width: 130 }, { prop: 'status', label: '状态', type: 'status' }
];
const rowActions = [
  { label: '查看证据', mode: 'detail' },
  { label: '人工确认', confirmMessage: '清仓、停售、归档等建议属于高风险决策。当前操作仅为流程占位，不会改变商品状态。', message: '生命周期确认接口尚未提供，当前保持 pending。' }
];
const detailFields = [
  { prop: 'review_id', label: '复盘编号' }, { prop: 'reason', label: '建议原因' }, { prop: 'review_period', label: '复盘周期' },
  { prop: 'rule_version', label: '规则版本' }, { prop: 'evidence', label: '分析证据', type: 'json' }
];
</script>
