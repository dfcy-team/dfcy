<template>
  <ol v-if="progress" class="fulfillment-progress" :class="{ compact }" aria-label="采购单履约进度">
    <li v-for="(step, index) in steps" :key="step.key" :class="step.state" :aria-label="`${index + 1} ${step.label}：${step.stateLabel}`">
      <template v-if="compact">
        <span class="compact-label">{{ step.label }}</span>
        <span class="compact-stage"><el-icon aria-hidden="true" class="stage-symbol"><CircleCheckFilled v-if="step.state==='complete'"/><RemoveFilled v-else/></el-icon><strong>{{ number(step.quantity) }}</strong></span>
        <small>{{index===0 && orderDate ? orderDate.slice(5) : number(step.remaining)}}</small>
      </template>
      <template v-else>
        <div class="step-heading"><span class="step-number">{{ index + 1 }}</span><strong class="step-label">{{ step.label }}</strong><el-tag size="small" :type="step.tagType">{{ step.stateLabel }}</el-tag></div>
        <div class="step-quantities"><strong>{{step.quantityLabel}}：{{ number(step.quantity) }} 件</strong><span v-if="step.remaining > 0">{{ step.remainingLabel }} {{ number(step.remaining) }} 件</span><span v-if="index===0 && orderDate">下单日期：{{orderDate}}</span><span v-if="index===1 && latestShipmentDate">最新发货日期：{{latestShipmentDate}}</span></div>
      </template>
    </li>
  </ol>
  <span v-else class="progress-missing">进度待加载</span>
</template>
<script setup>
import { computed } from 'vue';
import { CircleCheckFilled, RemoveFilled } from '@element-plus/icons-vue';
const props = defineProps({ progress: { type: Object, default: null }, compact: Boolean, orderDate:{type:String,default:''},latestShipmentDate:{type:String,default:''} });
const number = value => Number(value || 0).toLocaleString('zh-CN');
const steps = computed(() => {
  const p = props.progress || {};
  const ordered = Math.max(0, Number(p.ordered_quantity || 0));
  const stage = p.stage || '';
  const orderComplete = ordered > 0 && Boolean(stage) && stage !== 'draft' && stage !== 'cancelled';
  const makeStep = (key, label, quantity, remainingLabel, completeLabel = '已完成') => {
    const count = Math.max(0, Number(quantity || 0));
    const complete = orderComplete && (key === 'shipped' ? p.unshipped_quantity != null && Number(p.unshipped_quantity) === 0 : key === 'received' ? stage === 'completed' : key === 'dispatched' ? (p.undispatched_quantity != null ? Number(p.undispatched_quantity)===0 : ['awaiting_inbound','completed'].includes(stage)) : count >= ordered);
    const active = !complete && count > 0;
    const pendingByLine={shipped:p.unshipped_quantity,dispatched:p.undispatched_quantity,received:p.unreceived_quantity}[key];
    return { key, label, quantityLabel: ({ordered:'下单数量',shipped:'已发数量',dispatched:'已集货',received:'已入库'})[key], quantity: count, remaining: pendingByLine != null ? Math.max(0,Number(pendingByLine)) : Math.max(0, ordered-count), remainingLabel,
      state: complete ? 'complete' : active ? 'active' : 'pending',
      stateLabel: complete ? completeLabel : active ? '进行中' : '待开始',
      tagType: complete ? 'success' : active ? 'primary' : 'info' };
  };
  const order = makeStep('ordered', '下单', ordered, '待下单');
  order.state = orderComplete ? 'complete' : 'pending';
  order.stateLabel = orderComplete ? '已完成' : '待下单';
  order.tagType = orderComplete ? 'success' : 'info';
  return [
    order,
    makeStep('shipped', '发货', p.shipped_quantity, '未发'),
    makeStep('dispatched', '集货', p.dispatched_quantity, '待集货'),
    makeStep('received', '入库', p.received_quantity, '待入库')
  ];
});
</script>
<style scoped>
.fulfillment-progress{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:0;margin:0;list-style:none;gap:12px}.fulfillment-progress li{position:relative;display:flex;flex-direction:column;gap:7px;min-width:0;border-top:2px solid #dce3eb;padding:10px 0}.fulfillment-progress li.complete{border-color:#32a852}.fulfillment-progress li.active{border-color:#2563eb}.step-heading,.step-quantities{display:flex;align-items:center;gap:8px}.step-heading{min-height:26px}.step-number{display:grid;place-items:center;flex:none;width:24px;height:24px;border-radius:50%;background:#e2e8f0;color:#475569;font-size:13px;font-weight:600}.complete .step-number{background:#2563eb;color:#fff}.active .step-number{background:#2563eb;color:#fff}.step-label{font-size:14px;color:#172033}.step-quantities{align-items:baseline;justify-content:space-between;flex-wrap:wrap}.step-quantities>strong{font-size:13px;color:#172033;font-variant-numeric:tabular-nums}.step-quantities>span{font-size:12px;color:#64748b}.compact{gap:2px;min-width:250px}.compact li{display:flex;flex-direction:column;justify-content:center;gap:2px;border:0;padding:1px 3px;min-height:30px}.compact-label{display:none;font-size:10px;color:#64748b;white-space:nowrap}.compact-stage{display:flex;align-items:center;gap:5px;white-space:nowrap}.compact-stage i{font-style:normal;font-size:12px;color:#aab4c2}.complete .compact-stage i{color:#32a852}.active .compact-stage i{color:#2563eb}.compact .compact-stage strong{font-size:12px;color:#344256;font-variant-numeric:tabular-nums}.compact .active .compact-stage strong{color:#1d4ed8}.compact small{padding-left:18px;color:#7b8797;font-size:10px;font-variant-numeric:tabular-nums}.progress-missing{font-size:12px;color:#64748b}@media(max-width:600px){.fulfillment-progress{gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}.compact{grid-template-columns:repeat(4,minmax(0,1fr));gap:1px}}
.fulfillment-progress:not(.compact)>li{border:0;padding:5px 0}.fulfillment-progress:not(.compact) .step-heading:after{content:'';flex:1;min-width:12px;height:1px;background:#dce3eb;margin-left:5px}.fulfillment-progress:not(.compact) .complete .step-heading:after,.fulfillment-progress:not(.compact) .active .step-heading:after{background:#9bb9fb}.fulfillment-progress:not(.compact) .step-quantities{display:flex;flex-direction:column;align-items:flex-start;gap:4px;margin-left:32px}.fulfillment-progress:not(.compact) .step-quantities>strong{font-size:12px;font-weight:400;color:#64748b}.fulfillment-progress:not(.compact) .step-heading .el-tag{flex-shrink:0}
.compact{gap:0;min-width:250px}.compact li{position:relative;min-height:30px;padding:0 2px}.compact li:not(:last-child):after{content:'';height:1px;background:#dce3ed;position:absolute;left:54px;right:3px;top:8px}.compact .stage-symbol{font-size:13px;color:#c1c8d3;flex:none}.compact .complete .stage-symbol{color:#32ae4d}.compact .active .stage-symbol{color:#2463ff}.compact-stage{gap:4px;position:relative;z-index:1;width:max-content;background:var(--el-table-tr-bg-color,#fff)}.compact strong{font-weight:400}.compact small{font-size:10px;padding-left:17px}.step-number{width:26px;height:26px;font-size:14px}.step-label{font-size:13px}.fulfillment-progress:not(.compact) .step-quantities{margin-left:44px;gap:1px}.fulfillment-progress:not(.compact)>li{padding:0;gap:4px}.fulfillment-progress:not(.compact) .step-heading{gap:10px}.fulfillment-progress:not(.compact) .step-quantities>span{font-size:12px;line-height:16px}.fulfillment-progress:not(.compact) .step-quantities>strong{line-height:16px}.fulfillment-progress:not(.compact) .step-heading:after{background:#dbe3f0}.fulfillment-progress:not(.compact) .complete .step-heading:after{background:#9dbbff}
.compact li:not(:last-child):after{display:none}.compact .compact-stage{width:auto;background:transparent}.compact .compact-stage strong{flex:none}.compact li:not(:last-child) .compact-stage:after{content:'';flex:1;min-width:3px;height:1px;background:#dce3ed;margin-left:4px}
</style>
