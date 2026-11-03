<template>
  <section class="cost-detail" aria-label="商品成本明细">
    <button v-if="canBack" :disabled="loading" class="back" @click="$emit('back')">← 返回订单列表</button>
    <div class="cost-summary">
      <p><strong>{{ cost.partial ? '已知成本合计' : '成本合计' }}：{{ money(cost.known_amount) }} {{ cost.currency }}</strong></p>
      <p>涉及 {{ cost.order_count }} 个订单／调整记录；{{ cost.pending_orders }} 个成本待核，{{ cost.missing_items }} 项商品明细待核。</p>
      <p v-if="cost.classification_pending" class="pending">{{ cost.classification_pending }} 个订单分类依据待核；不推定为正常订单或已退货入库。</p>
      <p v-if="cost.original_totals.length">原币已知成本：<span v-for="item in cost.original_totals" :key="item.currency">{{ money(item.amount) }} {{ item.currency }} </span>（支出绝对值）</p>
      <p v-if="cost.partial" class="pending">尚有未获取的成本或汇率，当前金额不代表完整成本。</p>
    </div>
    <details class="cost-basis">
      <summary>成本口径及汇率来源（{{ cost.quotes.length }} 种汇率）</summary>
      <p>成本归属日：{{ cost.date_from || '未获取' }}<template v-if="cost.date_to !== cost.date_from"> 至 {{ cost.date_to }}</template>。按结算日有效的已确认成本版本计算，按成本归属月份业务汇率折算。</p>
      <p>数量依据为订单商品及有效调整明细；没有退货入库依据时不自动冲回成本。</p>
      <p v-if="!cost.quotes.length">汇率未获取，或原币与展示币种相同，无需换算。</p>
      <div v-for="(quote, i) in cost.quotes" :key="i" class="quote">
        <p>{{ quote.period }}：1 {{ quote.from }} = {{ quote.rate }} {{ quote.to }}；汇率记录 #{{ quote.input_id }}</p>
        <small>{{ quote.source }}</small><small v-if="quote.source_hash">来源 SHA256：{{ quote.source_hash }}</small>
      </div>
    </details>
    <section v-if="cost.categories?.length" class="cost-categories">
      <h4>商品成本分类构成</h4>
      <p>成本支出为负，回冲为正；退款不等于退货入库。分类待核与成本金额待核分别保留。</p>
      <table><thead><tr><th>成本构成</th><th>涉及订单数</th><th>金额（{{ cost.currency }}）</th><th>核算状态</th></tr></thead>
        <tbody><tr v-for="row in cost.categories" :key="row.key"><td>{{ row.label }}</td><td>{{ row.order_count }}</td><td class="num">{{ money(row.amount) }}</td><td>{{ row.state }}</td></tr></tbody>
      </table>
      <p>分类成本与已有回冲净额合计：{{ money(cost.category_total) }} {{ cost.currency }}。</p>
    </section>
    <h4>{{ cost.level === 'orders' ? '成本与回冲归属明细' : 'SKU 成本明细' }}</h4>
    <p v-if="cost.cross_month_returns">以前月份成本在本期的回冲：{{ cost.cross_month_returns.count }} 笔，{{ money(cost.cross_month_returns.amount) }} {{ cost.currency }}。缺少日期或入库依据的记录继续待核。</p>
    <div class="cost-scroll">
      <table v-if="cost.level === 'orders'">
        <thead><tr><th>订单／店铺</th><th>流水类型</th><th>原成本日期</th><th>本次归属日期</th><th>金额（{{ cost.currency }}）</th><th>核验／关联</th></tr></thead>
        <tbody><tr v-for="row in cost.rows" :key="row.key">
          <td><button :disabled="loading" class="link" @click="$emit('drill', row.key)">{{ row.order }}</button><small>{{ row.shop }} · 查看 SKU、数量及版本</small></td>
          <td>{{ row.event }}<small>{{ row.category_label }}</small><small v-if="row.cross_month">跨月回冲</small><details v-if="row.classification_reason" class="version"><summary>分类依据</summary><small>{{ row.classification_reason }}</small><small v-if="row.classification_evidence">原始状态：{{ row.classification_evidence.raw_status || '未获取' }}；标准状态：{{ row.classification_evidence.order_status || '未获取' }}<br />商品行状态：{{ row.classification_evidence.item_statuses?.join('、') || '未获取' }}<br />退款状态：{{ row.classification_evidence.refund_statuses.join('、') || '无关联记录' }}<br />回仓状态：{{ row.classification_evidence.return_statuses.join('、') || '无关联记录' }}<br />关联送样：{{ row.classification_evidence.sample_ids.join('、') || '无' }}</small><small v-if="row.classification_evidence?.platform_logistics">平台物流：{{ row.classification_evidence.platform_logistics.label }}（{{ row.classification_evidence.platform_logistics.status }}）<br />事件时间：{{ row.classification_evidence.platform_logistics.occurred_at_utc }}<br />来源：{{ row.classification_evidence.platform_logistics.source }}</small></details></td>
          <td>{{ row.original_date || '未获取' }}</td><td>{{ row.accounting_date || '未获取' }}</td>
          <td class="num"><button :disabled="loading" class="link" @click="$emit('drill', row.key)">{{ money(row.amount) }}</button><small v-if="row.pending">已知部分</small></td>
          <td>{{ row.pending ? '成本待核' : '成本已核算' }}<small>{{ row.relation }}</small><small v-for="item in row.original" :key="item.currency">原币：{{ money(item.amount) }} {{ item.currency }}</small><small v-for="reason in row.reasons.slice(0, 2)" :key="reason">{{ reason }}</small></td>
        </tr></tbody>
      </table>
      <table v-else>
        <thead><tr><th>商品／SKU</th><th>累计数量</th><th>单件成本</th><th>原币成本合计</th><th>成本金额（{{ cost.currency }}）</th><th>状态</th></tr></thead>
        <tbody><tr v-for="row in cost.rows" :key="row.key">
          <td>{{ row.sku }}<small v-if="row.legacy">旧编码：{{ row.legacy }}</small>
            <details v-if="row.version_id" class="version"><summary>成本版本 #{{ row.version_id }}／v{{ row.version_no }}</summary><small>有效期：{{ row.effective_from || '未获取' }} 至 {{ row.effective_to || '未结束' }}</small><small>仓库 ID：{{ row.warehouse_id ?? '未指定' }}</small></details>
          </td>
          <td class="num">{{ row.quantity ?? '—' }}</td>
          <td class="num">{{ unitCost(row.unit_cost) }}<small>{{ row.original_currency }}</small></td>
          <td class="num">{{ money(row.original_amount) }}<small>{{ row.original_currency }}{{ row.original_partial ? ' · 已知部分' : '' }}</small></td>
          <td class="num">{{ money(row.amount) }}</td>
          <td>{{ row.pending ? '待核' : '已核算' }}<small v-for="reason in row.reasons" :key="reason">{{ reason }}</small><small v-if="row.source">{{ row.source }}</small></td>
        </tr></tbody>
      </table>
    </div>
    <div class="cost-pages"><span>{{ cost.total }} 条 · {{ cost.page }} / {{ pages }}</span><button :disabled="loading || cost.page <= 1" @click="$emit('page', cost.page - 1)">上一页</button><button :disabled="loading || cost.page >= pages" @click="$emit('page', cost.page + 1)">下一页</button></div>
    <details v-if="cost.level !== 'orders' && cost.flows?.total" class="cost-flows">
      <summary>成本与回冲归属明细（{{ cost.flows.total }} 笔）</summary>
      <div class="cost-scroll"><table><thead><tr><th>订单／店铺</th><th>流水类型</th><th>原成本日期</th><th>本次归属日期</th><th>金额（{{ cost.currency }}）</th><th>核验／关联</th></tr></thead>
        <tbody><tr v-for="row in cost.flows.rows" :key="row.key"><td>{{ row.order }}<small>{{ row.shop }}</small></td><td>{{ row.event }}<small>{{ row.category_label }}</small><small v-if="row.cross_month">跨月回冲</small></td><td>{{ row.original_date || '未获取' }}</td><td>{{ row.accounting_date || '未获取' }}</td><td class="num">{{ money(row.amount) }}</td><td>{{ row.pending ? '成本待核' : '成本已核算' }}<small>{{ row.relation }}</small></td></tr></tbody>
      </table></div>
      <div class="flow-pages"><span>{{ cost.flows.total }} 条 · {{ cost.flows.page }} / {{ flowPages }}</span><button :disabled="loading || cost.flows.page <= 1" @click="$emit('flow-page', cost.flows.page - 1)">上一页</button><button :disabled="loading || cost.flows.page >= flowPages" @click="$emit('flow-page', cost.flows.page + 1)">下一页</button></div>
    </details>
  </section>
</template>

<script setup>
import { computed } from 'vue';
const props=defineProps({cost:{type:Object,required:true},money:{type:Function,required:true},loading:Boolean,canBack:Boolean});
defineEmits(['drill','page','flow-page','back']);
const pages=computed(()=>Math.max(1,Math.ceil(props.cost.total/props.cost.page_size)));
const flowPages=computed(()=>Math.max(1,Math.ceil((props.cost.flows?.total||0)/(props.cost.flows?.page_size||20))));
function unitCost(value){if(value==null)return'—';const [whole,fraction='']=String(value).split('.');return whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+'.'+fraction.replace(/0+$/,'').padEnd(2,'0');}
</script>

<style scoped>
.cost-categories{margin:18px 0}.cost-categories p,.cost-detail>p{line-height:1.6}h4{margin:18px 0 8px}.cost-categories th{position:static}.cost-flows{margin-top:20px}.cost-flows>summary{cursor:pointer;margin-bottom:10px;color:#365b89}.flow-pages{display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-top:12px}
.cost-detail{font-size:13px;color:#253753}.cost-summary{background:#f5f8fd;border:1px solid #dce5f3;padding:10px 14px;margin:12px 0}.cost-summary p{margin:5px 0;line-height:1.6}.pending{color:#975800}.cost-basis{margin:14px 0;line-height:1.6}.cost-basis summary,.version summary{cursor:pointer;color:#365b89}.quote{padding:8px 0;border-bottom:1px solid #dce5f3}.quote p{margin:0}.cost-scroll{max-height:55vh;overflow:auto;border:1px solid #dce5f3}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:10px 8px;border-bottom:1px solid #dce5f3;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#eff4fa;white-space:nowrap}td{overflow-wrap:anywhere}tbody tr:nth-child(even){background:#f5f8fd}.num{white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}small{display:block;color:#526176;font-size:11px;line-height:1.6;white-space:normal;overflow-wrap:anywhere}.version{margin-top:5px;min-width:140px;max-width:240px}.cost-pages{display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-top:12px}button{font:inherit;border:1px solid #c6d3e5;border-radius:4px;background:#fff;color:#29466e;padding:7px 10px;cursor:pointer}button:disabled{opacity:.55;cursor:default}.link{padding:0;border:0;color:#294f8b;background:transparent;text-align:left}.link:hover{text-decoration:underline}.back{margin-bottom:8px}
</style>
