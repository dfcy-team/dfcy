<template>
  <div class="audit-trail">
    <el-empty v-if="!events.length" description="暂无操作记录" :image-size="55" />
    <article v-for="(event, index) in events" :key="index">
      <header><strong>{{ actions[event.action] || event.action }}</strong><span>{{ event.actor__username || `用户 #${event.actor_id}` }} · {{ time(event.created_at) }}</span></header>
      <p v-if="event.masked_detail?.reason">原因：{{ event.masked_detail.reason }}</p>
      <dl v-if="event.action === 'correct' || event.action === 'edit'"><template v-for="change in changes(event)" :key="change.key"><dt>{{ change.label }}</dt><dd><del>{{ change.before }}</del><span>→ {{ change.after }}</span></dd></template></dl>
      <p v-if="event.to_status" class="state">处理后状态：{{ statuses[event.to_status] || event.to_status }}</p>
    </article>
  </div>
</template>

<script setup>
defineProps({ events: { type: Array, default: () => [] }, statuses: { type: Object, default: () => ({}) } });
const actions = { create: '新建草稿', edit: '编辑草稿', correct: '更正登记', register: '确认已付款并登记', void: '作废登记', submit: '提交审批', approve: '审批通过', reject: '驳回', withdraw: '撤回', cancel: '取消登记', delete: '删除草稿（可恢复）', restore: '恢复登记', detail_updated: '内部明细已更新', detail_update_failed: '明细更新失败', evidence_upload: '上传凭证' };
const fields = { order_amount: '整单金额', fee_amount: '服务费', fee_currency: '服务费币种', exchange_rate: '兑换汇率', rate_date: '汇率日期', rate_source: '汇率来源', cost: '整单成本', currency: '币种', amount: '实际金额', paid_at: '付款日期', type: '类型', recipient: '收款人', phone: '手机号', payment_account: '付款账户', transaction_reference: '交易参考号', reason: '原因', note: '备注', changes: '商品变化' };
const time = value => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
function display(value) { if (Array.isArray(value)) return value.map(row => `${({ add: '增加', reduce: '减少', replace: '替换' })[row.action] || '变化'}：${row.old_sku_id ? `原商品 #${row.old_sku_id} 减${row.reduce_quantity}` : ''}${row.new_sku_id ? ` 新商品 #${row.new_sku_id} 加${row.add_quantity}` : ''}`).join('；') || '—'; return ({ refund: '退款', other: '其他' })[value] || String(value ?? '') || '—'; }
function changes(event) { const { before = {}, after = {} } = event.masked_detail || {}; return Object.entries(fields).filter(([key]) => JSON.stringify(before[key]) !== JSON.stringify(after[key])).map(([key, label]) => ({ key, label, before: display(before[key]), after: display(after[key]) })); }
</script>

<style scoped>
.audit-trail article { padding: 14px 0; border-bottom: 1px solid #e2e8ec; } header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; font-size: 13px; } header span, p, dd { color: #475569; font-size: 12px; line-height: 1.8; } p { margin: 8px 0 0; } dl { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: 6px 12px; margin: 10px 0; font-size: 13px; } dt { color: #334155; } dd { margin: 0; overflow-wrap: anywhere; } dd del { margin-right: 8px; } dd span { color: #172033; }.state { font-size: 12px; }
</style>
