<template>
  <section class="finance-native" aria-label="平台账单财务汇总">
    <header class="page-heading">
      <h1>平台账单</h1>
      <details v-if="batch" class="batch-caption"><summary>{{ batch.source?.data_origin === 'saas_database' ? 'SaaS数据库批次' : '已验收批次' }} · 设置版本 {{ batch.revision }}</summary><p>{{ batch.label }} · {{ batch.can_edit ? '调整保存到本地 SaaS，保留操作记录' : '当前为只读权限' }}</p><p>各级汇总共用订单核算明细；费用先归属订单，再聚合店铺／国家、分配SKU／原成交商品链接。原始金额、成本和汇率依据不变。</p></details>
      <button :disabled="loading || saving || rebuilding || sourceBlocked" @click="batch?.can_edit && batch.source?.database_scope ? rebuild() : refresh()">{{ batch?.can_edit && batch.source?.database_scope ? '重新汇总' : '刷新批次' }}</button>
      <button v-if="batch" :disabled="saving || sourceBlocked" @click="advanced = true">广告及账务设置</button>
      <button v-if="batch?.can_edit && batch.source?.database_scope" :disabled="loading || saving || rebuilding" @click="openCoverage">汇总范围</button>
    </header>
    <section v-if="sourceBlocked || error || autoError" class="summary-status" role="alert">
      <strong>{{ sourceBlocked ? '汇总暂不可用：批次文件未就绪' : '本次汇总未完成' }}</strong>
      <p>{{ sourceBlocked ? '财务批次文件目录未配置或文件缺失。请管理员恢复原批次文件；自动汇总已暂停，账务数据未被清空。' : error || autoError }}</p>
      <button :disabled="loading || rebuilding" @click="refresh">重新检查</button>
    </section>
    <p v-else-if="batch?.source?.database_scope" class="auto-summary" role="status">{{ rebuilding ? rebuildStatus + '；当前保留上次汇总结果。' : '后台每5分钟检查，仅自动更新本月和上月；历史账期保留原结果，需手动重新汇总。' }}<span v-if="batch.automation?.scope"> 自动范围：{{ batch.automation.scope.from }} 至 {{ batch.automation.scope.to }}，适用于全部汇总维度及流水明细。</span></p>
    <el-alert v-else-if="batch?.source_changed" title="来源数据已更新；当前展示已验收批次，请核对并接入新批次。" type="warning" :closable="false" />
    <el-alert v-if="dateWarning" :title="dateWarning" type="warning" :closable="false" />
    <div v-if="batch?.source?.database_scope" class="view-options"><span>已纳入：{{ batch.source.database_scope.from }} 至 {{ batch.source.database_scope.to }} · {{ batch.source.database_scope.stores.length }} 家店铺</span><span>生成时间：{{ formatTime(batch.imported_at) }}</span><button @click="rebuildHistoryOpen = true">汇总记录</button><button v-if="dateWarning" :disabled="loading" @click="showUnresolvedDates">查看待补日期费用</button></div>
    <template v-if="!sourceBlocked">
    <section v-if="batch" class="period-context" aria-label="统计周期">
      <nav class="period-types" aria-label="统计维度"><button v-for="period in periodTypes" :key="period[0]" :data-period-type="period[0]" :aria-pressed="draft.period_type === period[0]" :disabled="loading || saving || rebuilding" @click="changePeriodType(period[0])">{{ period[1] }}</button></nav>
      <div class="period-fields">
        <label>账期<select v-model="draft.month" :disabled="loading || saving || rebuilding" @change="applyPeriod"><option value="" :disabled="draft.period_type !== 'month'">全部账期</option><option v-for="m in availableMonths" :key="m">{{ m }}</option></select></label>
        <label v-if="draft.period_type !== 'month'">统计区间<select v-model="draft.period" :disabled="loading || saving || rebuilding" @change="applyPeriod"><option v-for="interval in availablePeriods" :key="interval.value" :value="interval.value">{{ interval.label }}</option><option value="undated">待归期（无可靠日期）</option></select></label>
      </div>
    </section>
    <section v-if="batch" class="attribution-context" aria-label="费用归属">
      <div class="view-options"><button data-attribution="assigned" :aria-pressed="attributionArea === 'assigned'" :disabled="loading || saving" @click="changeAttribution('assigned')">已归属订单汇总</button><button data-attribution="pending" :aria-pressed="attributionArea === 'pending'" :disabled="loading || saving" @click="changeAttribution('pending')">待归属订单明细（{{ loading ? '核对中' : (attribution.pending_rows || 0) + '条非零金额' }}）</button><span>{{ attributionArea === 'pending' ? '仅核对原额，不计入正式利润；参考项另行标记。' : '利润仅包含已归属订单的收支；不代表商品、成本和日期已全部核对。' }}</span></div>
      <details><summary>归属对账：参与汇总原额＝已归属订单＋待归属订单（{{ mode === 'operations' ? '运营' : '财务' }}口径）</summary><p class="detail-note">按当前账期、统计区间、国家、平台、店铺和币种核对，不随商品关键词及明细字段筛选缩小；不同币种不合计。未关联／未分摊的仓库处理费及仓库其他费不参与本次汇总，也不进入待核对，原登记保留不动。</p><div class="attribution-scroll"><table class="parts"><thead><tr><th>国家</th><th>科目</th><th>币种</th><th>参与汇总原额</th><th>已归属订单</th><th>待归属订单</th></tr></thead><tbody><tr v-for="item in attributionTotals" :key="item.country + item.currency + item.kind"><td>{{ item.country }}</td><td>{{ item.label }}</td><td>{{ item.currency }}</td><td>{{ money(item.total) }}</td><td>{{ money(item.assigned) }}</td><td>{{ money(item.pending) }}<small v-if="item.unknown_rows">另有{{ item.unknown_rows }}条金额未确认</small></td></tr></tbody></table></div><p v-for="item in attribution.item_gaps || []" :key="item.store" class="detail-note">{{ item.store }}：{{ item.orders }}个订单仍有商品归属待核，其中内部SKU待关联{{ item.sku_orders }}单、商品链接待关联{{ item.link_orders }}单；两项可能重叠，不认定分摊完成。</p></details>
    </section>
    <div class="view-bar">
      <nav aria-label="汇总级别"><button v-for="tab in views" :key="tab[0]" :data-view="tab[0]" :aria-current="view === tab[0] ? 'page' : undefined" :disabled="saving" @click="changeView(tab[0])">{{ tab[1] }}</button></nav>
      <span class="count">{{ loading ? '正在核对结果数量…' : total.toLocaleString() + (view === 'detail' ? (attributionArea === 'pending' ? ' 条待归属明细' : ' 条原始流水（不分摊）') : ' 组') }}</span>
      <button v-if="view === 'detail' && batch?.can_edit && !options.raw_flows" :disabled="loading || saving" @click="editFee()">新增费用</button>
      <button v-if="view === 'detail'" @click="showHistory(1)">操作记录</button>
    </div>
    <form v-if="batch" class="filters" @submit.prevent="search">
      <label>国家<select v-model="draft.country" @change="draft.store = ''"><option value="">全部国家</option><option v-for="(name, key) in options.countries" :key="key" :value="key">{{ name }}</option></select></label>
      <label>平台<select v-model="draft.platform" @change="draft.store = ''"><option value="">全部平台</option><option value="lazada">Lazada</option><option value="shopee">Shopee</option></select></label>
      <label>店铺<select v-model="draft.store"><option value="">全部店铺</option><option v-for="shop in availableStores" :key="shop.id" :value="shop.id">{{ shop.code }}</option></select></label>
      <label>展示币种<select v-model="draft.currency"><option value="">{{ view === 'detail' ? '全部币种' : '全部当地币种' }}</option><option v-for="currency in currencies" :key="currency">{{ currency }}</option></select></label>
      <label v-if="view === 'order' || view === 'detail'">订单号<input v-model="draft.order" placeholder="完整或部分订单号" /></label>
      <label v-if="view === 'sku'">SKU 编码<input v-model="draft.sku" placeholder="内部／旧编码／平台 SKU" /></label>
      <label v-if="view === 'product_link'">商品名称／商品ID<input v-model="draft.product" /></label>
      <template v-if="view === 'detail'">
        <label>开始日期<input v-model="draft.from" type="date" /></label><label>结束日期<input v-model="draft.to" type="date" /></label>
        <label>费用科目<select v-model="draft.kind"><option value="">全部科目</option><option v-for="kind in options.kinds" :key="kind.key" :value="kind.key">{{ kind.label }}</option></select></label>
        <label>费用名称／来源<input v-model="draft.keyword" /></label>
        <label>状态<select v-model="draft.status"><option value="">全部状态</option><option value="normal">正常</option><template v-if="!options.raw_flows"><option value="modified">已修改</option><option value="added">新增费用</option><option value="disabled">已禁用</option></template><option value="pending">待核</option><option value="readonly">只读</option></select></label>
        <label v-if="!options.raw_flows">可调整<select v-model="draft.editable"><option value="">全部记录</option><option value="1">仅可调整</option></select></label>
      </template>
      <button type="submit" :disabled="loading || saving">查询</button><button type="button" :disabled="loading || saving" @click="reset">重置</button>
    </form>
    <p v-if="periodNote && (view !== 'detail' || !options.raw_flows)" class="detail-note" role="note">{{ appliedPeriodLabel }} · {{ periodNote }}</p>
    <div v-if="view === 'detail' || view === 'sku'" class="view-options">
      <span v-if="view === 'detail'">原始费用逐笔展示，不分摊。成本按出库日期、退货冲回按成功入库日期；金额调整请到原登记页面，取消登记后重新汇总即移除。净结算仅供核对，不与收入和手续费重复相加。仅有来源月份的记录不推断具体日期。</span>
      <label v-if="view === 'detail' && !options.raw_flows">流水口径<select v-model="mode" :disabled="loading || saving" @change="loadTable(1)"><option value="operations">运营</option><option value="finance">财务</option></select></label>
      <label v-if="view === 'sku'">汇总范围<select v-model="scope" :disabled="loading || saving" @change="loadTable(1)"><option value="store">店铺 SKU</option><option value="product">内部 SKU</option></select></label>
    </div>
    <div v-if="view !== 'detail'" class="view-options" aria-label="财务指标展示方式">
      <span>费率、毛利率与利润率</span><button v-for="item in [['percentage','百分比'],['amount','金额']]" :key="item[0]" :aria-pressed="metricDisplay === item[0]" @click="metricDisplay = item[0]">{{ item[1] }}</button><span>仅切换下方指标展示；保留金额正负号。</span>
    </div>
    <div v-if="loading || saving" class="query-progress" role="status">{{ saving ? '正在校验并保存费用…' : queryStatus || '正在加载当前条件的汇总…' }}<small v-if="loading">完成后自动显示结果，无需重复点击查询。可切换汇总级别查看其他结果。</small></div>
    <div ref="tableBox" class="table-scroll" :aria-busy="loading || saving">
      <table v-if="view !== 'detail'" class="summary-table" :inert="loading || saving" :style="{width: tableWidth + 'px'}"><colgroup><col v-for="col in identityColumns" :key="col.key" :style="{width:col.width + 'px'}" /><col v-for="col in amountColumns" :key="col.key" style="width:132px" /><col v-for="rate in displayRates" :key="rate[0]" style="width:150px" /><col style="width:170px" /><col style="width:90px" /></colgroup>
        <thead><tr class="bands"><th :colspan="identityColumns.length" class="identity-band">归属信息</th><th colspan="4">订单收支</th><th colspan="3">店铺费用</th><th colspan="5">业务成本与费用</th><th :colspan="displayRates.length || 1">{{ metricDisplay === 'percentage' ? '费率、毛利率与利润率' : '费用、毛利与利润金额' }}</th><th colspan="2">结果与核对</th></tr>
          <tr><th v-for="col in identityColumns" :key="col.key" class="identity-cell" :style="{left:col.left + 'px'}">{{ col.label }}</th><th v-for="col in amountColumns" :key="col.key">{{ col.label }}</th><th v-for="rate in displayRates" :key="rate[0]">{{ metricLabel(rate) }}</th><th>已归属订单利润</th><th>待核对</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.key" :data-row-key="row.key">
          <td v-for="col in identityColumns" :key="col.key" class="identity-cell" :style="{left:col.left + 'px'}" :class="{ product:col.key === 'title' }"><template v-if="col.key === 'title'"><span>{{ row.identity.title || '平台商品' }}</span><small v-if="row.identity.product_id">商品ID · {{ row.identity.product_id }}</small><a v-if="safeUrl(row.identity.url)" :href="row.identity.url" target="_blank" rel="noopener noreferrer">打开商品链接 ↗</a></template><template v-else>{{ identity(row, col.key) }}</template></td>
          <td v-for="col in amountColumns" :key="col.key"><button class="amount" :class="sign(row.values[col.key])" :disabled="loading || saving" @click="showDetail(row, col.key)">{{ money(row.values[col.key], col.key === 'adjustment' ? '—' : '金额待确认') }}</button><small v-if="row.partial[col.key]">已知部分 · 待核</small></td>
          <td v-for="rate in displayRates" :key="rate[0]" class="metric-cell"><div v-for="key in metricKeys(rate[0])" :key="key" :class="{ 'metric-pair': metricKeys(rate[0]).length > 1 }"><small v-if="metricKeys(rate[0]).length > 1">{{ key.includes('operations') ? '运营' : '财务' }}</small><button class="amount" :class="sign(metricAmount(row,key))" @click="showDetail(row, 'rate:' + key)">{{ metricDisplay === 'percentage' ? signedRate(row.rates[key], metricAmount(row,key)) : money(metricAmount(row,key)) }}</button></div><small v-if="metricKeys(rate[0]).some(key => row.partial[key] || (key === 'gross_margin' && row.partial.product_cost) || (key.startsWith('profit_') && row.pending))">试算 · 缺项待核</small></td>
          <td class="profit"><div v-for="m in ['operations', 'finance']" :key="m"><small>{{ m === 'operations' ? '运营' : '财务' }}</small><button class="amount" :class="sign(row.profits[m])" @click="showDetail(row, 'profit_' + m)">{{ money(row.profits[m]) }}</button></div><small v-if="row.pending">试算 · 缺项待核</small></td><td>{{ row.pending ? '待核' : '已汇总' }}</td>
        </tr></tbody>
      </table>
      <table v-else class="ledger-table" :inert="loading || saving"><thead><tr><th>日期</th><th>国家</th><th>店铺</th><th>订单号</th><th>费用科目</th><th>口径</th><th>原金额</th><th>{{ attributionArea === 'pending' ? '待归属金额（非利润）' : '计入金额' }}</th><th>币种</th><th>状态</th><th>来源／费用名称／原因</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.key"><td>{{ row.date }}</td><td>{{ row.identity.country }}</td><td>{{ row.identity.shop }}</td><td>{{ row.identity.order || '—' }}</td><td>{{ row.label }}</td><td>{{ {both:'双口径',operations:'运营',finance:'财务'}[row.mode] }}</td><td>{{ money(row.original_amount) }}</td><td><button class="amount" :class="sign(row.amount)" @click="showDetail(row, row.kind)">{{ money(row.amount) }}</button></td><td>{{ row.identity.currency }}</td><td>{{ row.status }}</td><td class="description">{{ row.source }}<small>{{ row.description }}</small></td><td class="actions"><template v-if="row.editable && batch?.can_edit"><button :disabled="loading || saving" @click="editFee(row)">修改</button><button :disabled="loading || saving" @click="editFee(row, row.disabled ? 'restore' : 'disable')">{{ row.disabled ? '恢复' : '禁用' }}</button><button v-if="row.added" :disabled="loading || saving" @click="editFee(row, 'delete')">删除</button></template><span v-else>只读</span></td></tr></tbody>
      </table>
      <p v-if="!loading && !rows.length" class="empty">{{ error ? '汇总结果加载失败，请重新检查；此处不代表金额为零。' : '当前筛选条件下没有记录，可调整账期或重置筛选。' }}</p>
    </div>
    <footer class="pagination"><span>统一订单核算明细 · {{ loading ? '正在加载当前页…' : '当前页 ' + rows.length + ' 条' }}</span><button :disabled="page <= 1 || loading || saving" @click="loadTable(page - 1)">上一页</button><span>{{ loading ? '— / —' : page + ' / ' + Math.max(1, Math.ceil(total / 20)) }}</span><button :disabled="page * 20 >= total || loading || saving" @click="loadTable(page + 1)">下一页</button></footer>

    </template>
    <el-drawer v-model="detailOpen" :title="detail?.title || '金额构成'" size="min(850px, 95vw)" destroy-on-close>
      <p v-if="detailLoading" role="status">{{ detailStatus || '正在加载构成…' }}</p><el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <template v-if="detail"><p v-if="detail.sales != null && !detail.cost">本行订单销售额：{{ money(detail.sales) }}；金额合计：{{ money(detail.amount) }}</p><p class="detail-note">{{ detail.note }}</p>
        <FinanceCostDetail v-if="detail.cost" :cost="detail.cost" :money="money" :loading="detailLoading" :can-back="!!detailQuery?.source_key" @drill="showSource" @page="changeCostPage" @flow-page="changeCostFlowPage" @back="readDetail(detailParams)" />
        <table v-if="detail.parts?.length" class="parts"><thead><tr><th>子项</th><th>金额</th><th>占本行销售额</th></tr></thead><tbody><tr v-for="(part, i) in detail.parts" :key="i"><td :style="{paddingLeft: ((part.level || 2) - 1) * 12 + 'px'}"><strong v-if="part.subtotal">{{ part.label }}</strong><template v-else>{{ part.label }}</template><small v-if="part.status === 'reference'">仅核对，不计入</small><small v-if="part.status === 'pending'">待核</small><small v-if="part.source">{{ part.source }}</small></td><td :class="sign(part.amount)">{{ money(part.amount) }}</td><td>{{ signedRate(part.rate, part.amount) }}</td></tr></tbody><tfoot><tr><th>合计（分类小计不重复计入）</th><td :class="sign(detail.amount)">{{ money(detail.amount) }}</td><td>{{ signedRate(detail.rate, detail.amount) }}</td></tr></tfoot></table>
        <details v-if="detail.records?.length"><summary>来源明细（{{ detail.records.length }} 笔）</summary><table class="parts"><tbody><tr v-for="(record, i) in detail.records" :key="i"><td>{{ record.date }}<small>{{ record.shop }} · {{ record.order }}</small></td><td>{{ record.description || record.source }}</td><td><button class="amount" @click="showSource(record.key)">{{ money(record.amount) }}</button></td></tr></tbody></table></details>
        <iframe v-if="detail.html" :srcdoc="sourceDocument(detail.html)" title="原始金额来源" sandbox="" class="source-frame" />
      </template>
    </el-drawer>
    <el-dialog v-model="editorOpen" :title="operationLabel + '费用'" width="620px" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
      <form class="fee-form" @submit.prevent="submitFee"><label>店铺<select v-model="fee.store" :disabled="!!fee.id"><option v-for="shop in options.stores" :key="shop.id" :value="shop.id">{{ shop.code }}</option></select></label><label>账期<input v-model="fee.month" type="month" :disabled="!!fee.id" required /></label><label>日期<input v-model="fee.date" type="date" :disabled="!!fee.id" required /></label><label>费用科目<select v-model="fee.kind" :disabled="!!fee.id"><option v-for="k in options.kinds" :key="k.key" :value="k.key">{{ k.label }}</option></select></label><label>口径<select v-model="fee.mode" :disabled="!!fee.id || fee.kind !== 'advertising'"><option value="both" :disabled="fee.kind === 'advertising'">双口径</option><option value="operations">运营</option><option value="finance">财务</option></select></label><label>订单号<input v-model="fee.order" :disabled="!!fee.id || fee.kind === 'advertising'" placeholder="留空为店铺公共费用" /></label><label>金额（支出为负数）<input v-model="fee.amount" inputmode="decimal" :disabled="fee.operation !== 'save'" required /></label><label class="full">变更原因<textarea v-model="fee.reason" required maxlength="1000" /></label><el-alert v-if="feeError" class="full" :title="feeError" type="error" :closable="false" /><div class="full actions"><button type="button" :disabled="saving" @click="editorOpen = false">取消</button><button type="submit" :disabled="saving">{{ saving ? '正在校验保存…' : operationLabel + '并更新汇总' }}</button></div></form>
    </el-dialog>
    <el-drawer v-model="historyOpen" title="费用操作记录" size="min(850px, 95vw)" destroy-on-close><p v-if="historyLoading" role="status">{{ historyStatus || '正在加载操作记录…' }}</p><p v-if="historyError">{{ historyError }}</p><table class="parts"><thead><tr><th>时间／操作</th><th>归属与金额</th><th>原因</th></tr></thead><tbody><tr v-for="(item, index) in history.rows" :key="index"><td>{{ new Date(item.at).toLocaleString('zh-CN') }}<small>{{ {save:'保存',disable:'禁用',restore:'恢复',delete:'删除'}[item.operation] }}</small></td><td>{{ options.stores.find(s => s.id === item.after?.store)?.code || item.after?.store }} · {{ item.after?.month }}<small>{{ options.kinds.find(k => k.key === item.after?.kind)?.label || item.after?.kind }} · {{ money(item.after?.amount) }}</small></td><td>{{ item.after?.reason }}</td></tr></tbody></table><p v-if="!historyLoading && !historyError && !history.rows.length">暂无费用操作记录。</p><button :disabled="historyLoading || history.page <= 1" @click="showHistory(history.page - 1)">上一页</button><span> {{ history.page }} / {{ Math.max(1, Math.ceil(history.total / 20)) }} </span><button :disabled="historyLoading || history.page * 20 >= history.total" @click="showHistory(history.page + 1)">下一页</button></el-drawer>
    <el-dialog v-model="advanced" title="广告及账务设置" width="min(1180px, 96vw)" top="3vh" destroy-on-close @closed="refresh"><FinanceSummary v-if="advanced" tools-only :initial-context="legacyContext" /></el-dialog>
    <el-dialog v-model="coverageOpen" title="汇总范围" width="min(620px,95vw)" :close-on-click-modal="false">
      <p>重新汇总读取当前范围内的 SaaS 数据。纳入新月份或店铺时，请在此扩大范围；保留已有账期和店铺。不会补采平台数据。</p>
      <form class="fee-form" @submit.prevent="confirmCoverage"><label>开始日期<input v-model="coverage.from" type="date" required /></label><label>结束日期<input v-model="coverage.to" type="date" required /></label><fieldset class="full coverage-stores"><legend>店铺（已选 {{ coverage.stores.length }} 家）</legend><label v-for="shop in batch?.scope_stores || []" :key="shop.id"><input v-model="coverage.stores" type="checkbox" :value="shop.id" />{{ shop.code }}</label></fieldset><p class="full">新结果通过校验后才替换当前批次；原批次保留用于追溯。</p><div class="full actions"><button type="button" @click="coverageOpen = false">取消</button><button type="submit" :disabled="rebuilding || !coverage.stores.length">按此范围重新汇总</button></div></form>
    </el-dialog>
    <el-dialog v-model="rebuildHistoryOpen" title="汇总记录" width="min(850px,95vw)"><p>仅展示本租户最近 10 次任务，失败任务不会替换已通过校验的批次。</p><table class="parts"><thead><tr><th>提交时间</th><th>来源 → 结果批次</th><th>状态</th><th>完成时间</th></tr></thead><tbody><tr v-for="job in batch?.rebuild_history || []" :key="job.id"><td>{{ formatTime(job.created_at) }}</td><td>{{ job.dataset_id }} → {{ job.result_dataset_id || '—' }}</td><td>{{ jobLabel(job.status) }}</td><td>{{ formatTime(job.finished_at) }}</td></tr></tbody></table><p v-if="!batch?.rebuild_history?.length">暂无汇总任务记录。</p></el-dialog>
  </section>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { fetchFinanceSummary, fetchFinanceSummaryJob, rebuildFinanceSummary, fetchFinanceSummaryTable, fetchFinanceSummaryDetail, saveFinanceSummaryFee, fetchFinanceSummaryHistory } from '../../api/financeReconciliation';
import FinanceCostDetail from './FinanceCostDetail.vue';
const FinanceSummary = defineAsyncComponent(() => import('./FinanceSummary.vue'));
const views = [['country','国家汇总'],['store','店铺汇总'],['order','订单汇总'],['sku','SKU汇总'],['product_link','商品链接汇总'],['detail','流水明细']];
const periodTypes = [['month','月度'],['week','周度'],['half_month','半月']];
const amountColumns = [['sales','订单销售额'],['refund','订单退款'],['order_fee','订单费用'],['adjustment','订单调整'],['shop_adjustment','店铺调整'],['operations','运营口径广告花费'],['finance','财务口径广告花费'],['product_cost','商品成本'],['gcash','GCash退款'],['promotion','刷单费用'],['warehouse_order','仓库处理费'],['warehouse_other','仓库其他处理费']].map(([key,label])=>({key,label}));
const blank = () => ({month:'2026-09',period_type:'month',period:'',country:'',platform:'',store:'',currency:'',order:'',sku:'',product:'',from:'',to:'',kind:'',keyword:'',status:'',editable:''});
const batch=ref(null),rows=ref([]),options=ref({stores:[],countries:{},months:[],kinds:[]}),rateFields=ref([]),view=ref('store'),mode=ref('operations'),scope=ref('store'),page=ref(1),total=ref(0),loading=ref(false),saving=ref(false),rebuilding=ref(false),error=ref(''),tableBox=ref(null),advanced=ref(false);
const attributionArea=ref('assigned'),attribution=ref({totals:[],pending_rows:0,item_gaps:[]});let assignedView='store';
const attributionTotals=computed(()=>attribution.value.totals.filter(item=>item.mode===mode.value));
const draft=reactive(blank());let applied=blank(),requestVersion=0,alive=true;const tabMemory={};
const sourceBlocked=computed(()=>batch.value?.source_available===false);
const coverageOpen=ref(false),rebuildHistoryOpen=ref(false),coverage=reactive({from:'',to:'',stores:[]});
const formatTime=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
const jobLabel=value=>({queued:'等待执行',running:'计算中',ready:'已完成',failed:'失败，原批次保留',blocked:'权限已变化',superseded:'已被新版本替代'}[value]||value);
function openCoverage(){Object.assign(coverage,{...batch.value.source.database_scope,stores:[...batch.value.source.database_scope.stores]});coverageOpen.value=true;}
async function confirmCoverage(){const scope={...coverage,stores:[...coverage.stores]};coverageOpen.value=false;await rebuild(false,scope);}
async function showUnresolvedDates(){
  attributionArea.value='assigned';view.value='detail';
  Object.assign(draft,blank(),{month:applied.month,period_type:applied.period_type,period:applied.period,country:applied.country,platform:applied.platform,store:applied.store,currency:applied.currency,kind:'warehouse_order',status:'pending'});
  applied={...draft};await loadTable(1,true);
}

const autoError=ref('');let autoTimer,checking=false;
const dateWarning=ref(''),periodNote=ref('');
const availableMonths=computed(()=>[...new Set([...options.value.months,...[batch.value?.automation?.scope?.from,batch.value?.automation?.scope?.to].filter(Boolean).map(day=>day.slice(0,7))])].sort().reverse());
const availablePeriods=computed(()=>options.value.periods_by_month?.[draft.month]?.[draft.period_type]||[]);
const appliedPeriodLabel=ref('月度分摊');
function normalizePeriod(){if(draft.period_type==='month'){draft.period='';return;}if(!draft.month)draft.month=options.value.months[0]||'2026-09';if(draft.period!=='undated'&&!availablePeriods.value.some(r=>r.value===draft.period))draft.period=availablePeriods.value[0]?.value||'undated';}
function periodLabel(filters,data){const type=filters.period_type||'month',name=({week:'周度分摊',half_month:'半月分摊',month:'月度分摊'})[type],interval=filters.period==='undated'?'待归期':data.periods_by_month?.[filters.month]?.[type]?.find(r=>r.value===filters.period)?.label;return name+' · '+(filters.month||'全部账期')+(interval?' · '+interval:'');}
const queryStatus=ref(''),detailStatus=ref(''),rebuildStatus=ref('');const pollWaiters=new Map();
function waitForPoll(){return new Promise(resolve=>{const timer=window.setTimeout(()=>{pollWaiters.delete(timer);resolve();},1500);pollWaiters.set(timer,resolve);});}
async function calculation(response,current,status){
  let data=result(response);const started=Date.now();
  while(data?.job){
    if(!current())throw Error('查询已取消');
    if(data.job.status==='ready')return data.result;
    if(data.job.error_code==='BROKER_UNAVAILABLE')throw Error('后台任务服务暂不可用，原结果未更改；请稍后重新检查。');
    if(Date.now()-started>900000)throw Error('等待已超过15分钟，已停止本页轮询；后台任务未被取消，请查看汇总记录后重新检查。');
    if(!data.pending){const failure=Error(({superseded:'来源或设置版本已变化，请刷新批次后重试。',blocked:'权限已变化，请重新登录并核对访问权限。',failed:'后台计算失败，原批次保持不变，请重试。'})[data.job.status]||'计算未完成，请重试。');failure.code=data.job.status;throw failure;}
    if(status)status.value=data.job.status==='queued'?'后台任务排队中，等待计算资源…':'后台正在计算并校验，完成后自动更新…';
    if(status)status.value+=' 已等待 '+Math.floor((Date.now()-started)/1000)+' 秒';
    await waitForPoll();
    if(!current())throw Error('查询已取消');
    data=result(await fetchFinanceSummaryJob(data.job.id));
  }
  return data;
}
const availableStores=computed(()=>options.value.stores.filter(s=>(!draft.country||s.country===draft.country)&&(!draft.platform||s.platform===draft.platform)));
const currencies=computed(()=>[...new Set(options.value.stores.map(s=>s.currency).filter(Boolean).concat(view.value === 'detail' ? options.value.currencies || ['CNY'] : []))]);
const identityColumns=computed(()=>{const cols=[{key:'country',label:'国家'}];if(view.value!=='country')cols.push({key:'platform',label:'平台'},{key:'shop',label:'店铺'});if(view.value==='order')cols.push({key:'order',label:'订单号'});if(view.value==='sku')cols.push({key:'sku',label:'商品／SKU'});if(view.value==='product_link')cols.push({key:'title',label:'商品链接／商品ID'},{key:'sku_count',label:'SKU数'});cols.push({key:'currency',label:'币种'});let left=0;return cols.map(col=>{const width={country:90,platform:90,shop:105,order:185,sku:260,title:280,sku_count:70,currency:70}[col.key];const result={...col,width,left};left+=width;return result;});});
const metricDisplay=ref('percentage');
const displayRates=computed(()=>{
  const ordered=[...rateFields.value];
  const gross=ordered.findIndex(([key])=>key==='gross_margin');
  if(gross>=0)ordered.unshift(...ordered.splice(gross,1));
  return ordered.filter(([key])=>!['finance','profit_finance'].includes(key)).map(([key,label])=>[key,key==='operations'?'广告费率':key==='profit_operations'?'利润率':label]);
});
const metricKeys=key=>key==='operations'?['operations','finance']:key==='profit_operations'?['profit_operations','profit_finance']:[key];
const metricLabel=([key,label])=>metricDisplay.value==='percentage'?label:({gross_margin:'毛利',operations:'广告花费',profit_operations:'利润'}[key]||amountColumns.find(col=>col.key===key)?.label||label);
function metricAmount(row,key){
  if(key.startsWith('profit_'))return row.profits[key.slice(7)];
  if(key==='gross_margin'){
    if(row.values.sales==null||row.values.product_cost==null)return null;
    const cents=BigInt(money(row.values.sales).replace(/[,.]/g,''))+BigInt(money(row.values.product_cost).replace(/[,.]/g,''));
    const absolute=cents<0n?-cents:cents;
    return (cents<0n?'-':'')+(absolute/100n)+'.'+String(absolute%100n).padStart(2,'0');
  }
  return row.values[key];
}
function signedRate(rate,value){if(value==null||!rate||!/^[-+]?\d+(?:\.\d+)?%$/.test(rate))return '—';const magnitude=rate.replace(/^[-+]/,'');return Number(value)<0&&parseFloat(magnitude)!==0?'-'+magnitude:magnitude;}
const tableWidth=computed(()=>identityColumns.value.reduce((sum,c)=>sum+c.width,0)+12*132+170+90+displayRates.value.length*150);
const legacyContext=computed(()=>({view:view.value,mode:mode.value,page:page.value,fields:{...applied},skuScope:scope.value}));
function identity(row,key){return key==='platform'?({lazada:'Lazada',shopee:'Shopee'}[row.identity[key]]||row.identity[key]||'—'):row.identity[key]??'—';}
function money(value,missing='—') {if(value==null)return missing;const text=String(value),negative=text.startsWith('-'),[whole,fraction='']=text.replace(/^[+-]/,'').split('.');let cents=BigInt(whole||'0')*100n+BigInt((fraction+'00').slice(0,2));if(Number(fraction[2]||0)>=5)cents++;const units=(cents/100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g,',');return(negative&&cents!==0n?'-':'')+units+'.'+(cents%100n).toString().padStart(2,'0');}
const sign=value=>value==null?'unknown':Number(value)<0?'negative':Number(value)>0?'positive':'';
const safeUrl=value=>typeof value==='string'&&/^https:\/\/(?:www\.)?(?:lazada\.(?:com\.ph|co\.th|com\.my|sg|co\.id|vn)|shopee\.(?:ph|co\.th|com\.my|sg|co\.id|vn))\//i.test(value);
function params(number=page.value){return{view:view.value,mode:mode.value,scope:scope.value,page:number,page_size:20,filter_attribution:attributionArea.value,...Object.fromEntries(Object.entries(applied).map(([k,v])=>['filter_'+k,v]))};}
function result(response){if(!response?.success){const failure=Error(response?.message||'请求未完成，请重试');failure.http_status=response?.http_status;if(failure.http_status===403||failure.http_status===401){rows.value=[];attribution.value={totals:[],pending_rows:0,item_gaps:[]};batch.value=null;dateWarning.value='';periodNote.value='';}throw failure;}return response.data;}
async function refresh(){const version=++requestVersion;loading.value=true;error.value='';try{const data=result(await fetchFinanceSummary({native:1}));if(!alive||version!==requestVersion)return;if(data.dataset!==batch.value?.dataset||data.revision!==batch.value?.revision)rows.value=[];batch.value=data;autoError.value='';if(sourceBlocked.value){rows.value=[];total.value=0;loading.value=false;return;}await loadTable(page.value);await rebuildIfChanged();}catch(e){if(alive&&version===requestVersion){batch.value=null;rows.value=[];error.value=e.message;loading.value=false;}}}
async function rebuild(automatic=false,scopeOverride=null){if(loading.value||saving.value||rebuilding.value||!batch.value||sourceBlocked.value)return;rebuilding.value=true;rebuildStatus.value='正在读取SaaS数据并提交后台汇总…';error.value='';autoError.value='';try{const data=await calculation(await (scopeOverride ? rebuildFinanceSummary(batch.value.dataset,batch.value.revision,scopeOverride) : rebuildFinanceSummary(batch.value.dataset,batch.value.revision)),()=>alive,rebuildStatus);if(!alive)return;rows.value=[];batch.value=data;await loadTable(automatic?page.value:1,!automatic);}catch(e){if(alive){if(e.code==='superseded'){await refresh();return;}if(automatic)autoError.value='自动汇总未完成，保留原结果，稍后重试：'+e.message;else error.value=e.message;}}finally{if(alive)rebuilding.value=false;}}
function autoIdle(){return alive&&!document.hidden&&!loading.value&&!saving.value&&!rebuilding.value&&!advanced.value&&!editorOpen.value&&!detailOpen.value&&!historyOpen.value&&!coverageOpen.value&&!rebuildHistoryOpen.value;}
async function rebuildIfChanged(){if(batch.value?.automation?.mode!=='server'&&autoIdle()&&!sourceBlocked.value&&batch.value?.can_edit&&batch.value?.source?.database_scope&&batch.value.source_changed)await rebuild(true);}
async function checkForChanges(){
  if(checking||!autoIdle()||!batch.value?.source?.database_scope)return;
  checking=true;const version=requestVersion;
  try{
    const data=result(await fetchFinanceSummary({native:1}));
    if(!autoIdle()||version!==requestVersion)return;
    const changed=sourceBlocked.value||data.dataset!==batch.value.dataset||data.revision!==batch.value.revision;
    batch.value=data;autoError.value='';
    if(sourceBlocked.value)return;
    if(changed){rows.value=[];await loadTable(page.value);}
    await rebuildIfChanged();
  }catch(e){if(alive)autoError.value='自动检测暂未完成，稍后重试：'+e.message;}
  finally{checking=false;}
}
async function loadTable(number=1,resetPosition=false){if(!batch.value)return;const version=++requestVersion;loading.value=true;queryStatus.value='';rows.value=[];total.value=0;page.value=number;error.value='';dateWarning.value='';periodNote.value='';attribution.value={totals:[],pending_rows:0,item_gaps:[]};try{let data;
for(let attempt=0;attempt<2;attempt++){
  try{data=await calculation(await fetchFinanceSummaryTable(batch.value.dataset,params(number)),()=>alive&&version===requestVersion,queryStatus);break;}
  catch(e){
    if(e.code!=='superseded'||attempt||!alive||version!==requestVersion)throw e;
    queryStatus.value='批次已更新，正在读取最新汇总…';
    const latest=result(await fetchFinanceSummary({native:1}));
    if(!alive||version!==requestVersion)return;
    batch.value=latest;
    if(sourceBlocked.value)return;
  }
}
if(!alive||version!==requestVersion)return;rows.value=data.rows;attribution.value=data.attribution||{totals:[],pending_rows:0,item_gaps:[]};dateWarning.value=[data.period_warning,data.date_warning].filter(Boolean).join(' ');periodNote.value=data.period_note||'';appliedPeriodLabel.value=periodLabel(applied,data.options);total.value=data.total;page.value=data.page;options.value=data.options;rateFields.value=data.rate_fields;batch.value.revision=data.revision;await nextTick();if(resetPosition&&tableBox.value){tableBox.value.scrollTop=0;tableBox.value.scrollLeft=0;}}catch(e){if(alive&&version===requestVersion){rows.value=[];error.value=e.message;}}finally{if(alive&&version===requestVersion)loading.value=false;}}
function search(){normalizePeriod();applied={...draft};loadTable(1,true);}
function applyPeriod(){normalizePeriod();for(const key of ['month','period_type','period'])applied[key]=draft[key];loadTable(1,true);}
function changePeriodType(value){if(value===draft.period_type)return;draft.period_type=value;applyPeriod();}
function reset(){const period={month:applied.month,period_type:applied.period_type,period:applied.period};Object.assign(draft,blank(),period);search();}
function changeAttribution(value){if(value===attributionArea.value||loading.value||saving.value)return;attributionArea.value=value;rows.value=[];total.value=0;if(value==='pending'){assignedView=view.value;delete tabMemory.detail;if(view.value!=='detail'){changeView('detail',true);return;}const common=Object.fromEntries(['month','period_type','period','country','platform','store','currency'].map(k=>[k,applied[k]]));Object.assign(draft,blank(),common);applied={...draft};}else if(view.value!==assignedView){changeView(assignedView);return;}loadTable(1,true);}
function changeView(value,keepAttribution=false){if(value===view.value||saving.value)return;if(!keepAttribution)attributionArea.value='assigned';tabMemory[view.value]={draft:{...draft},applied:{...applied}};const common=Object.fromEntries(['month','period_type','period','country','platform','store','currency'].map(k=>[k,applied[k]]));view.value=value;rows.value=[];const saved=tabMemory[value];Object.assign(draft,{...blank(),...saved?.draft,...common});applied={...draft,...saved?.applied,...common};loadTable(1,true);}
const detailOpen=ref(false),detail=ref(null),detailLoading=ref(false),detailError=ref(''),detailQuery=ref(null);let detailRequest=0,detailParams=null;
async function showDetail(row,kind){detailParams={...params(),row_key:row.key,kind};await readDetail(detailParams);}
async function showSource(key){await readDetail({...detailParams,source_key:key,cost_page:1});}
function changeCostFlowPage(number){readDetail({...detailQuery.value,flow_page:number});}
function changeCostPage(number){const query={...detailQuery.value,cost_page:number};if(!query.source_key)detailParams=query;readDetail(query);}
async function readDetail(query){const version=++detailRequest;detailQuery.value=query;detailOpen.value=true;detail.value=null;detailError.value='';detailStatus.value='';detailLoading.value=true;try{const data=await calculation(await fetchFinanceSummaryDetail(batch.value.dataset,query),()=>alive&&detailOpen.value&&version===detailRequest,detailStatus);if(alive&&version===detailRequest)detail.value=data;}catch(e){if(alive&&version===detailRequest)detailError.value=e.message;}finally{if(alive&&version===detailRequest)detailLoading.value=false;}}
const sourceDocument=html=>'<html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><style>body{font:13px sans-serif;color:#253753}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #dce4ef;text-align:left}small{display:block}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>'+html+'</body></html>';
const editorOpen=ref(false),fee=ref({}),feeError=ref('');const operationLabel=computed(()=>({save:fee.value.id?'修改':'新增',disable:'禁用',restore:'恢复',delete:'删除'}[fee.value.operation]||'修改'));
function editFee(row,operation='save'){const month=applied.month||options.value.months[0]||'2026-09';feeError.value='';fee.value=row?{id:row.edit_key||row.key,store:row.identity.store,month:row.record?.month||row.accounting_month||row.date.slice(0,7),date:row.accounting_date||row.date,kind:row.kind,mode:row.mode,order:row.identity.order||'',amount:money(row.record?.amount??row.original_amount??row.amount).replace(/,/g,''),reason:'',operation}:{store:applied.store||options.value.stores[0]?.id,month,date:month+'-01',kind:'order_fee',mode:'both',order:'',amount:'',reason:'',operation};editorOpen.value=true;}
watch(()=>fee.value.kind,kind=>{if(!fee.value.id){fee.value.mode=kind==='advertising'?'operations':'both';if(kind==='advertising')fee.value.order='';}});
async function submitFee(){if(saving.value)return;saving.value=true;feeError.value='';try{const data=result(await saveFinanceSummaryFee(batch.value.dataset,{revision:batch.value.revision,record:{...fee.value}}));batch.value.revision=data.revision;editorOpen.value=false;await loadTable(page.value);}catch(e){feeError.value=e.message+'；请核对当前版本和操作记录后重试。';await refresh();}finally{saving.value=false;}}
const historyOpen=ref(false),history=ref({rows:[],total:0,page:1}),historyError=ref(''),historyLoading=ref(false),historyStatus=ref('');let historyRequest=0;
async function showHistory(number){const version=++historyRequest;historyOpen.value=true;historyError.value='';historyStatus.value='';historyLoading.value=true;history.value={rows:[],total:0,page:number};try{const data=await calculation(await fetchFinanceSummaryHistory(batch.value.dataset,{page:number}),()=>alive&&historyOpen.value&&version===historyRequest,historyStatus);if(alive&&version===historyRequest)history.value=data;}catch(e){if(alive&&version===historyRequest)historyError.value=e.message;}finally{if(alive&&version===historyRequest)historyLoading.value=false;}}
onMounted(()=>{refresh();autoTimer=window.setInterval(checkForChanges,30000);document.addEventListener('visibilitychange',checkForChanges);});
onBeforeUnmount(()=>{alive=false;requestVersion++;detailRequest++;historyRequest++;window.clearInterval(autoTimer);for(const [timer,resolve] of pollWaiters){window.clearTimeout(timer);resolve();}pollWaiters.clear();document.removeEventListener('visibilitychange',checkForChanges);});
</script>

<style scoped>
.query-progress{padding:12px 16px;background:#edf4ff;border:1px solid #c6d3e5;border-radius:4px;color:#29466e}
.view-options button[aria-pressed="true"]{background:#255ff2;color:#fff;border-color:#255ff2}
.metric-pair{display:flex;justify-content:space-between;gap:12px}.metric-pair small{margin:0}.metric-cell{text-align:right}

.summary-status{margin:16px 0;padding:16px 20px;border:1px solid #e9b8b8;background:#fff6f5;border-radius:8px;color:#782323}.summary-status p{margin:8px 0 14px;max-width:75ch;line-height:1.6}

.attribution-context{display:grid;gap:8px;padding:12px 0;border-bottom:1px solid #d7e1ef}.attribution-context summary{cursor:pointer;color:#29466e}.attribution-context button[aria-pressed="true"]{color:#fff;background:#255ff2;border-color:#255ff2}.attribution-scroll{overflow:auto;max-height:300px}.attribution-scroll th{position:static}.attribution-scroll .parts{margin:8px 0}
.period-types button:first-child,.period-types button:last-child{border-radius:4px}
.period-context{display:grid;gap:16px;padding:0 0 16px;border-bottom:1px solid #d7e1ef}.period-types{gap:8px;flex-wrap:wrap}.period-types button{margin:0;border-radius:4px;padding:10px 24px;font-weight:600}.period-types button[aria-pressed="true"]{color:#fff;background:#255ff2;border-color:#255ff2}.period-fields{display:flex;align-items:flex-end;flex-wrap:wrap;gap:12px 16px}.period-fields label{display:grid;gap:6px}.period-fields select{min-width:160px}.view-bar nav{flex-wrap:wrap;row-gap:8px}
.finance-native{display:grid;gap:12px;min-width:0;color:#253753;font-size:13px}.page-heading,.view-bar,.pagination,.view-options{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.page-heading h1{font-size:20px;color:#172033;margin:0}.batch-caption{flex:1;font-size:12px;color:#526176}.batch-caption summary{cursor:pointer}.batch-caption p{margin:6px 0}.filters{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px 16px}.filters label,.fee-form label{display:grid;gap:6px}.filters select{min-width:120px}.filters input{width:185px}button,select,input,textarea{font:inherit;border:1px solid #c6d3e5;border-radius:4px;background:#fff;color:#29466e;padding:8px 12px}button{cursor:pointer;white-space:nowrap}button:disabled{cursor:default;opacity:.55}button:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #255ff2;outline-offset:2px}nav{display:flex}nav button{border-radius:0;margin-right:-1px}nav button:first-child{border-radius:4px 0 0 4px}nav button:last-child{border-radius:0 4px 4px 0}nav button[aria-current]{color:white;background:#255ff2;border-color:#255ff2}.count{margin-left:auto;color:#526176}.view-options{font-size:12px;color:#526176}.view-options select{margin-left:8px}.table-scroll{position:relative;overflow:auto;max-height:clamp(300px,calc(100vh - 365px),650px);border:1px solid #d7e1ef;background:#fff;min-height:120px}.table-scroll table{border-collapse:separate;border-spacing:0;min-width:100%}th,td{padding:12px;vertical-align:top;text-align:left;border-bottom:1px solid #dce5f3;white-space:nowrap}th{font-size:12px;background:#eff4fa;position:sticky;top:32px;z-index:2}.bands th{top:0;height:32px;box-sizing:border-box;padding:7px 12px;background:#e7eef8;border-right:1px solid #fff}.summary-table tbody td:first-child,.ledger-table tbody td:first-child{position:sticky;left:0;background:#fff;z-index:1}.summary-table thead tr:last-child th:first-child,.ledger-table th:first-child{left:0;z-index:3}.ledger-table th{top:0}tbody tr:nth-child(even) td{background:#f5f8fd}.summary-table tbody tr:nth-child(even) td:first-child,.ledger-table tbody tr:nth-child(even) td:first-child{background:#f5f8fd}.identity-cell{position:sticky;background:#fff;z-index:2;overflow:hidden;text-overflow:ellipsis}.summary-table th.identity-cell{z-index:4;background:#eff4fa}.bands th.identity-band{left:0;z-index:5}.summary-table tbody tr:nth-child(even) .identity-cell{background:#f5f8fd}.summary-table{table-layout:fixed}.product{min-width:250px;max-width:280px;white-space:normal;line-height:1.6}.product>span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.product a{font-size:11px;color:#365b89;display:block;margin-top:8px}small{display:block;color:#526176;font-size:11px;line-height:1.6;margin-top:3px}.amount{padding:0;border:0;background:transparent;color:inherit;text-align:right;white-space:nowrap;min-width:42px;font-variant-numeric:tabular-nums}.amount:hover{text-decoration:underline}.negative{color:#ce2323}.positive{color:#087b39}.unknown{color:#60718a}.profit{min-width:145px}.profit>div{display:flex;justify-content:space-between;gap:16px}.profit small{display:inline}.description{min-width:250px;max-width:420px;white-space:normal;line-height:1.6}.actions{display:flex;gap:6px;flex-wrap:wrap}.actions button{padding:6px 10px}.loading{position:sticky;left:0;top:0;height:0;z-index:5;text-align:center;color:#29466e;pointer-events:none}.loading::first-line{background:#edf4ff}.pagination{justify-content:flex-end}.pagination>span:first-child{margin-right:auto;color:#64748b}.empty{padding:25px}.parts{border-collapse:collapse;width:100%;margin:16px 0}.parts th{position:static}.parts td{white-space:normal}.detail-note{font-size:12px;color:#526176;line-height:1.7}.source-frame{width:100%;height:70vh;border:0}.fee-form{display:grid;grid-template-columns:1fr 1fr;gap:16px}.fee-form .full{grid-column:1 / -1}.fee-form textarea{min-height:72px}@media(max-width:900px){.page-heading .batch-caption{order:4;flex-basis:100%}.count{margin-left:0}.table-scroll{max-height:55vh}.fee-form{grid-template-columns:1fr}}
.coverage-stores{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;max-height:260px;overflow:auto;border:1px solid #dce4ef;border-radius:6px;padding:12px}.coverage-stores label{display:flex;flex-direction:row;align-items:center;gap:6px}.coverage-stores input{min-width:0;width:auto;margin:0}@media(max-width:600px){.coverage-stores{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
