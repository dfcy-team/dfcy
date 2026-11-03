<template>
  <section v-if="segment">
    <h4>{{ title }}</h4>
    <p>运单号：{{ segment.tracking_number || '未提供' }} · 平台物流状态：{{ segment.logistics_status || segment.status || '未提供' }}</p>
    <p v-if="segment.first_mile_tracking_number || segment.last_mile_tracking_number">头程：{{ segment.first_mile_tracking_number || '未提供' }} · 尾程：{{ segment.last_mile_tracking_number || '未提供' }}</p>
    <p v-if="segment.number_query_status || segment.tracking_query_status">运单查询：{{ queryLabel(segment.number_query_status) }} · 轨迹查询：{{ queryLabel(segment.tracking_query_status) }}</p>
    <ol v-if="segment.events?.length">
      <li v-for="(event, index) in segment.events" :key="index">{{ formatField(event.occurred_at_utc, { format: 'datetime' }) }} UTC · {{ event.status || '—' }} · {{ event.description || '未提供描述' }}</li>
    </ol>
    <p v-else>平台尚未返回轨迹节点，不代表未发货或未退回。</p>
  </section>
</template>

<script setup>
import { formatField } from '../views/sales-management/display';
defineProps({ title: { type: String, required: true }, segment: { type: Object, default: null } });
function queryLabel(value) { return ({ ok: '已查询', unavailable: '未获取，请复查授权或稍后重试' })[value] || '未查询'; }
</script>
