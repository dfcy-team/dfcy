<template>
  <Phase3DecisionPage
    eyebrow="经营决策"
    title="经营预警"
    subtitle="集中处理库存、商品、财务、供应商、RPA 和数据异常。"
    boundary-note="预警不会直接触发真实平台、付款、商品状态变更或 RPA；处理动作必须由后端记录负责人、说明、证据和审计时间。"
    :loader="fetchBusinessAlerts"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="预警处理队列"
    table-note="业务预警等级不等同于架构问题等级"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { fetchBusinessAlerts } from '../../api/alerts';

const filters = [
  { key: 'status', label: '状态', options: [{ label: '待处理', value: 'open' }, { label: '已确认', value: 'acknowledged' }, { label: '处理中', value: 'in_progress' }, { label: '已解决', value: 'resolved' }, { label: '已忽略', value: 'ignored' }] },
  { key: 'level', label: '等级', options: [{ label: '高', value: 'high' }, { label: '中', value: 'medium' }, { label: '低', value: 'low' }] },
  { key: 'alert_type', label: '类型', options: [{ label: '库存不足', value: 'stockout' }, { label: 'RPA连续失败', value: 'rpa_failure' }, { label: '数据未更新', value: 'stale_data' }] }
];
const columns = [
  { prop: 'alert_id', label: '预警编号', width: 150 }, { prop: 'alert_type', label: '类型', width: 150 }, { prop: 'object_ref', label: '对象', width: 160 },
  { prop: 'level', label: '等级', type: 'status' }, { prop: 'status', label: '状态', type: 'status', width: 120 },
  { prop: 'owner', label: '负责人', width: 140 }, { prop: 'triggered_at', label: '触发时间', width: 160 }, { prop: 'silence_until', label: '静默至', width: 160 }
];
const rowActions = [
  { label: '处理记录', mode: 'detail' },
  { label: '确认处理', permission: 'alerts.manage', confirmMessage: '当前仅展示处理流程占位，不会触发预警关联的真实业务动作。', message: '预警处理接口尚未提供，当前保持 pending。' },
  { label: '关闭', permission: 'alerts.manage', confirmMessage: '关闭需填写处理说明和证据。当前仅展示审计要求，不会提交。', message: '预警关闭接口尚未提供，当前保持 pending。', type: 'danger' }
];
const detailFields = [
  { prop: 'alert_id', label: '预警编号' }, { prop: 'reason', label: '触发原因' }, { prop: 'rule_version', label: '规则版本' },
  { prop: 'dedupe_key', label: '去重键' }, { prop: 'handling_records', label: '处理记录', type: 'json' }
];
</script>
