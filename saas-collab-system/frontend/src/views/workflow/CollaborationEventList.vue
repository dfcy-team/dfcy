<template>
  <RPAResourcePage title="协同回填" note="审核飞书/微信Mock回填，不直接写入业务主数据。"
    boundary-note="回填必须经过Mock验签、时间戳和防重放校验；确认仅改变回填记录状态，真实平台保持禁用。"
    :loader="fetchCollaborationEvents" :columns="columns" :filters="filters" :row-actions="actions" empty-text="暂无待确认协同回填" />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { confirmCollaborationEvent, fetchCollaborationEvents, rejectCollaborationEvent } from '../../api/workflow';

const filters = [
  { key: 'channel', label: '渠道', options: ['wechat', 'feishu'] },
  { key: 'status', label: '状态', options: ['pending_confirmation', 'confirmed', 'rejected'] }
];
const columns = [
  { prop: 'event_id', label: '事件ID', width: 180 }, { prop: 'channel', label: '渠道' },
  { prop: 'event_type', label: '事件类型' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'payload_hash', label: '载荷哈希', width: 220 }, { prop: 'received_at', label: '接收时间', width: 180 }
];
const actions = [
  { label: '确认', permission: 'workflow.collaboration.confirm', disabled: (row) => row.status !== 'pending_confirmation', confirmMessage: '确认只更新回填记录，不直接改变业务状态。', handler: (row) => confirmCollaborationEvent(row.id, { note: 'Confirmed from UI-P4.' }) },
  { label: '驳回', type: 'danger', permission: 'workflow.collaboration.confirm', disabled: (row) => row.status !== 'pending_confirmation', confirmMessage: '确认驳回此Mock回填？', handler: (row) => rejectCollaborationEvent(row.id, { note: 'Rejected from UI-P4.' }) }
];
</script>
