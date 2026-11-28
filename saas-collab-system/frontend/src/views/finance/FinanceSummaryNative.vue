<template>
  <section class="finance-native" aria-label="平台账单财务汇总">
    <header class="page-heading">
      <div class="heading-copy"><h1>平台账单</h1><p>直接查看汇总，沿金额核对到原始记录</p></div>
      <button v-if="initialization || (batch && batch.can_view_settings !== false)" :disabled="!batch || saving || sourceBlocked || showingPrevious" @click="openSettings()">广告及账务设置</button>
      <button class="primary-action" :disabled="loading || saving || rebuilding || sourceBlocked" @click="batch?.direct_query ? refreshCurrent() : batch?.can_edit && batch.source?.database_scope ? rebuild() : refresh()">{{ batch?.direct_query ? '刷新结果' : batch?.can_edit && batch.source?.database_scope ? '更新汇总' : '刷新结果' }}</button>
    </header>
    <p v-if="batch?.direct_query && !directFlows && displayedResult?.source_read_at" class="query-progress" role="status">来源读取时间：{{ formatTime(displayedResult.source_read_at) }}。可点击“刷新结果”读取最新记录。</p>
    <p v-if="directFlows" class="query-progress" role="status">直接读取SaaS原始记录，不依赖已发布汇总。原始来源只读；不进行汇率折算、成本计算或分摊，广告日报不等于扣款流水。</p>
    <section v-if="(!directFlows && sourceBlocked) || error || (!directFlows && autoError)" class="summary-status" role="alert">
      <strong>{{ directFlows ? '原始流水读取未完成' : sourceBlocked ? '汇总暂不可用：批次文件未就绪' : '本次汇总未完成' }}</strong>
      <p>{{ !directFlows && sourceBlocked ? '财务批次文件目录未配置或文件缺失。请管理员恢复原批次文件；自动汇总已暂停，账务数据未被清空。' : error || autoError }}</p>
      <button :disabled="loading || rebuilding" @click="directFlows ? loadTable(1,true) : refresh()">重新检查</button>
    </section>
    <section v-if="batch?.automation_health && ['paused','stale','waiting'].includes(batch.automation_health.state)" class="summary-status" role="status"><strong>{{ batch.automation_health.message }}</strong><p>最近检查：{{ batch.automation_health.checked_at ? formatTime(batch.automation_health.checked_at) : '暂无记录' }}。{{ batch.automation_health.recovery }}</p></section>
    <p v-if="showingPrevious" class="query-progress" role="status">当前展示上次结果（设置版本 {{ displayedResult.revision }}）；{{ loading || rebuilding ? '正在更新，完成后自动替换' : '更新未完成，可重新检查' }}。暂不可编辑或展开明细。</p>
    <p v-if="backgroundRefresh" class="query-progress" role="status">{{ batch.refresh_job.phase === 'merging' ? '来源变更正在合并，60 秒窗口结束后自动汇总' : '后台汇总已排队或正在执行' }}；当前展示已生成结果。</p>
    <p v-if="backgroundFailed" class="query-progress" role="status">后台更新未完成，当前保留上次结果。可点击更新汇总重试。</p>
    <p v-if="rebuilding" class="query-progress" role="status">{{ rebuildStatus }}；当前保留上次汇总结果。</p>
    <el-alert v-if="!batch?.source?.database_scope && batch?.source_changed" title="来源数据已更新；当前展示已验收批次，请核对并接入新批次。" type="warning" :closable="false" />
    <el-alert v-if="dateWarning" :title="dateWarning" type="warning" :closable="false" />
    <template v-if="!sourceBlocked || directFlows">
    <form v-if="batch || initialization" class="filters scope-filters" aria-label="统计筛选" @submit.prevent="search">
      <FinancePeriodPicker :model-value="{period_type:draft.period_type,month:draft.month,period:draft.period}" :coverage="batch?.source?.database_scope || {}" :disabled="saving" @update:model-value="setPeriod" />
      <label>国家<select v-model="draft.country" @change="draft.store = ''"><option value="">全部国家</option><option v-for="(name,key) in options.countries" :key="key" :value="key">{{ name }}</option></select></label>
      <label>平台<select v-model="draft.platform" @change="draft.store = ''"><option value="">全部平台</option><option value="lazada">Lazada</option><option value="shopee">Shopee</option><option v-if="directFlows" value="tiktok">TikTok Shop</option></select></label>
      <label>店铺<select v-model="draft.store"><option value="">全部店铺</option><option v-for="shop in availableStores" :key="shop.id" :value="shop.id">{{ shop.code }}</option></select></label>
      <label>{{ view === 'detail' && options.raw_flows ? '原币币种' : '币种' }}<select v-model="draft.currency"><option value="">{{ view === 'detail' ? '全部币种' : '当地币种分列' }}</option><option v-for="currency in currencies" :key="currency">{{ currency }}</option></select></label>
      <label v-if="view === 'order'">订单号<input v-model="draft.order" placeholder="完整或部分订单号" /></label>
      <label v-if="view === 'sku'">SKU 编码<input v-model="draft.sku" placeholder="内部／旧编码／平台 SKU" /></label>
      <label v-if="view === 'product_link'">商品名称／商品ID<input v-model="draft.product" /></label>
      <button type="submit" class="primary-action" :disabled="saving || rebuilding || (loading && !hasDraftChanges())">查询</button><button type="button" :disabled="loading || saving" @click="reset">重置</button>
      <small v-if="hasDraftChanges()" class="filter-pending" role="status">筛选已修改，点击“查询”应用；当前结果仍对应上次查询条件。</small>
    </form>
    <div class="view-bar"><nav aria-label="汇总级别"><button v-for="tab in views" :key="tab[0]" :data-view="tab[0]" :aria-current="view === tab[0] ? 'page' : undefined" :disabled="saving" @click="changeView(tab[0])">{{ tab[1] }}</button></nav><button class="pending-link" :disabled="loading || saving" @click="changeAttribution(attributionArea === 'pending' ? 'assigned' : 'pending')">{{ attributionArea === 'pending' ? '返回汇总' : directFlows ? '归属待核（需汇总核对）' : '归属待核 ' + (attribution.pending_rows || 0) + ' 条' }}</button></div>
    <section class="table-workbench" aria-label="账单结果">
    <header class="result-toolbar"><div class="result-context"><span>{{ views.find(tab => tab[0] === view)?.[1] }} · {{ appliedPeriodLabel }}</span><span class="count">{{ displayedResult ? directFlows ? '当前页 ' + rows.length + ' 条原始记录' : (showingPrevious ? '上次结果 · ' : '') + total.toLocaleString() + (view === 'detail' ? (attributionArea === 'pending' ? ' 条待归属明细' : batch?.direct_query ? ' 条核算来源' : ' 条原始流水（不分摊）') : ' 组') : loading ? '正在核对结果数量…' : '未获取结果数量' }}</span></div><div class="result-actions"><div v-if="view === 'detail' && batch && attributionArea === 'assigned'" class="view-options" aria-label="流水来源"><button v-for="item in [['source','实时原始流水'],['summary',batch?.direct_query ? '核算来源明细' : '已发布批次明细']]" :key="item[0]" :data-flow-mode="item[0]" :aria-pressed="flowMode === item[0]" :disabled="loading || saving" @click="changeFlowMode(item[0])">{{ item[1] }}</button></div><button v-if="view === 'detail' && !directFlows && batch?.can_edit" class="primary-action" :disabled="loading || saving || showingPrevious" @click="editFee()">人工新增记录</button><button v-if="view === 'detail' && !directFlows && batch?.can_edit" :disabled="loading || saving || showingPrevious" @click="openSettings('recharge')">广告充值／税费登记</button><button v-if="view === 'detail' && !directFlows && !batch?.direct_query" :disabled="!batch" @click="showHistory(1)">操作记录</button><div v-if="view !== 'detail'" class="view-options" aria-label="财务指标展示方式"><button v-for="item in [['amount','金额'],['percentage','费率／利润率']]" :key="item[0]" :aria-pressed="metricDisplay === item[0]" @click="metricDisplay = item[0]">{{ item[1] }}</button></div><label v-if="view === 'sku'">汇总范围<select v-model="scope" :disabled="loading || saving" @change="loadTable(1)"><option value="store">店铺 SKU</option><option value="product">内部 SKU</option></select></label></div></header>
    <form v-if="view === 'detail' && (batch || directFlows)" class="filters flow-filters" aria-label="流水筛选" @submit.prevent="search">
      <label>计入科目<select v-model="draft.kind"><option value="">全部科目</option><option v-for="kind in options.kinds" :key="kind.key" :value="kind.key">{{ kind.label }}</option></select></label>
      <label v-if="!directFlows && !options.raw_flows">计算口径<select v-model="mode" :disabled="loading || saving" @change="loadTable(1)"><option value="operations">运营</option><option value="finance">财务</option></select></label>
      <label>{{ directFlows ? '原始状态' : '参与状态' }}<select v-model="draft.status"><option value="">全部状态</option><option value="normal">{{ directFlows ? '已确认' : options.raw_flows ? '已纳入汇总' : '正常' }}</option><template v-if="!directFlows"><option value="modified">已修改</option><option value="added">人工新增</option><option value="disabled">已排除</option></template><option value="pending">待核</option><option :value="directFlows ? 'reference' : 'readonly'">{{ directFlows ? '参考' : '只读' }}</option></select></label>
      <details class="flow-more"><summary>更多筛选</summary><div class="filters"><label>订单号<input v-model="draft.order" /></label><label>费用名称／来源<input v-model="draft.keyword" /></label><label>开始日期<input v-model="draft.from" type="date" /></label><label>结束日期<input v-model="draft.to" type="date" /></label><label v-if="!directFlows && !options.raw_flows">可调整<select v-model="draft.editable"><option value="">全部记录</option><option value="1">仅可调整</option></select></label></div></details>
      <button type="submit" :disabled="loading || saving">筛选流水</button>
    </form>
    <div v-if="loading || saving" class="query-progress" role="status">{{ saving ? '正在校验并保存费用…' : queryStatus || '正在加载当前条件的汇总…' }}<small v-if="loading">完成后自动显示结果，无需重复点击查询。可切换汇总级别查看其他结果。</small></div>
    <div ref="tableBox" class="table-scroll" :aria-busy="loading || saving">
      <table v-if="view !== 'detail'" class="summary-table" :inert="loading || saving || showingPrevious" :style="{width:tableWidth + 'px'}"><colgroup><col v-for="col in identityColumns" :key="col.key" :style="{width:col.width + 'px'}" /><col v-for="col in amountColumns" :key="col.key" style="width:132px" /><col v-for="rate in displayRates" :key="rate[0]" style="width:150px" /><col style="width:90px" /></colgroup>
        <thead><tr class="bands"><th :colspan="identityColumns.length" class="identity-band">归属信息</th><th colspan="4">订单收支</th><th colspan="3">店铺费用</th><th colspan="5">业务成本与费用</th><th :colspan="displayRates.length">核算结果</th><th rowspan="2">核对状态</th></tr><tr><th v-for="col in identityColumns" :key="col.key" class="identity-cell" :style="{left:col.left + 'px'}">{{ col.label }}</th><th v-for="col in amountColumns" :key="col.key">{{ col.label }}{{ metricDisplay === 'percentage' ? '占比' : '' }}</th><th v-for="rate in displayRates" :key="rate[0]">{{ metricLabel(rate) }}</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.key" :data-row-key="row.key">
          <td v-for="col in identityColumns" :key="col.key" class="identity-cell" :style="{left:col.left + 'px'}" :class="{product:col.key === 'title'}"><template v-if="col.key === 'title'"><span>{{ row.identity.title || '平台商品' }}</span><small v-if="row.identity.product_id">商品ID · {{ row.identity.product_id }}</small><a v-if="safeUrl(row.identity.url)" :href="row.identity.url" target="_blank" rel="noopener noreferrer">打开商品链接 ↗</a></template><template v-else>{{ identity(row,col.key) }}</template></td>
          <td v-for="col in amountColumns" :key="col.key" :data-field="col.key"><button class="amount" :class="sign(row.values[col.key])" :disabled="loading || saving" @click="showDetail(row,(metricDisplay === 'percentage' ? 'rate:' : '') + col.key)">{{ metricDisplay === 'percentage' ? signedRate(row.rates[col.key],row.values[col.key]) : money(row.values[col.key],col.key === 'adjustment' ? '—' : '金额待确认') }}</button><el-tooltip v-if="anomalyText(row,col.key,metricDisplay === 'percentage')" :content="anomalyText(row,col.key,metricDisplay === 'percentage')" placement="top"><button class="field-anomaly" :aria-label="anomalyText(row,col.key,metricDisplay === 'percentage')" :disabled="loading || saving" @click="showDetail(row,(metricDisplay === 'percentage' ? 'rate:' : '') + col.key)">ⓘ</button></el-tooltip></td>
          <td v-for="rate in displayRates" :key="rate[0]" class="metric-cell" :class="{profit:rate[0].startsWith('profit_')}" :data-field="rate[0]"><button class="amount" :class="sign(metricAmount(row,rate[0]))" :disabled="loading || saving" @click="showDetail(row,(metricDisplay === 'percentage' ? 'rate:' : '') + rate[0])">{{ metricDisplay === 'percentage' ? signedRate(row.rates[rate[0]],metricAmount(row,rate[0])) : money(metricAmount(row,rate[0])) }}</button><el-tooltip v-if="anomalyText(row,rate[0],metricDisplay === 'percentage')" :content="anomalyText(row,rate[0],metricDisplay === 'percentage')" placement="top"><button class="field-anomaly" :aria-label="anomalyText(row,rate[0],metricDisplay === 'percentage')" @click="showDetail(row,(metricDisplay === 'percentage' ? 'rate:' : '') + rate[0])">ⓘ</button></el-tooltip></td>
          <td>{{ row.pending ? '待核' : '已汇总' }}</td>
        </tr></tbody>
      </table>
      <table v-else class="ledger-table" :inert="loading || saving || showingPrevious"><thead><tr><th>发生日期／店铺</th><th>订单／流水号</th><th>流水类型</th><th>计入科目</th><th>原始金额／币种</th><th>折算金额／币种</th><th>适用口径</th><th>{{ directFlows ? '原始状态' : '参与状态' }}</th><th>来源／原因</th><th>操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.key"><td>{{ row.date }}<small>{{ row.identity.shop }}</small><small v-if="directFlows">{{ row.date_basis }}</small></td><td>{{ row.identity.order || '店铺公共记录' }}<small>{{ row.source_id || row.key }}</small></td><td>{{ row.flow_type || row.label }}</td><td>{{ row.label }}</td><td>{{ money(row.original_amount) }} {{ row.original_currency || row.identity.currency }}</td><td><span v-if="directFlows">未折算</span><button v-else class="amount" :class="sign(row.amount)" @click="showDetail(row,row.kind)">{{ money(row.amount) }}</button> {{ row.identity.currency }}<small v-if="row.conversion?.missing" class="unknown">缺少有效汇率</small><el-tooltip v-if="row.conversion && row.conversion.from !== row.conversion.to" :content="conversionText(row)"><span class="field-anomaly" tabindex="0" :aria-label="conversionText(row)">ⓘ</span></el-tooltip></td><td>{{ row.mode_label || {both:'双口径',operations:'运营',finance:'财务'}[row.mode] }}</td><td>{{ row.status }}</td><td class="description">{{ row.source }}<small>{{ row.description }}</small></td><td class="actions"><button @click="showDetail(row,row.kind)">详情</button><template v-if="row.participation && batch?.can_edit"><button v-if="row.participation.supported" :disabled="loading || saving || showingPrevious" @click="editFee(row,row.participation.excluded ? 'restore_source' : 'exclude_source')">{{ row.participation.excluded ? '恢复汇总' : '排除汇总' }}</button><el-tooltip v-else :content="row.participation.reason"><span tabindex="0">来源只读 ⓘ</span></el-tooltip></template><template v-else-if="row.editable && batch?.can_edit"><button :disabled="loading || saving || showingPrevious" @click="editFee(row)">修改</button><button :disabled="loading || saving || showingPrevious" @click="editFee(row,row.disabled ? 'restore' : 'disable')">{{ row.disabled ? '恢复' : '排除汇总' }}</button><button v-if="row.added" :disabled="loading || saving || showingPrevious" @click="editFee(row,'delete')">删除</button></template><el-tooltip v-else :content="directFlows || batch?.direct_query ? '原始来源只读，请到对应费用登记或来源模块修改。' : !batch?.can_edit ? '当前账号没有账单调整权限' : row.edit_block_reason || '来源只读，请核对对应核算来源'"><span tabindex="0">来源只读 ⓘ</span></el-tooltip></td></tr></tbody></table>
      <p v-if="!loading && !rows.length" class="empty">{{ directFlows ? (error ? '原始流水读取未完成，请重试；不代表金额为零。' : '当前条件下未找到原始流水，可调整日期或筛选；未读取数量不按零金额处理。') : error ? '汇总结果加载失败，请重新检查；此处不代表金额为零。' : '当前筛选条件下没有记录，可调整账期或重置筛选。' }}</p>
    </div>
    <div v-if="displayedResult && summaryTotals.length" class="period-totals" aria-label="完整范围合计"><span class="totals-scope">{{ view === 'detail' ? '店铺账期合计（不随流水科目及原币筛选）' : '当前筛选全部结果合计' }}</span><span v-for="item in summaryTotals" :key="item.currency"><strong>{{ item.currency }}</strong>　销售额 {{ money(item.sales) }}　运营利润 {{ money(item.operations) }}　财务利润 {{ money(item.finance) }}<el-tooltip v-if="item.partial" content="包含缺项或待核来源，仅为已知部分合计"><span class="field-anomaly" role="note" aria-label="合计包含缺项，仅为已知部分">ⓘ</span></el-tooltip></span></div>
    <footer class="pagination"><span>{{ directFlows ? '原始流水明细' : '统一订单核算明细' }} · {{ displayedResult ? (showingPrevious ? '上次结果 · ' : '') + '当前页 ' + rows.length + ' 条' : loading ? '正在加载当前页…' : '未获取' }}</span><button :disabled="page <= 1 || loading || saving || showingPrevious" @click="loadTable(page - 1)">上一页</button><span>{{ displayedResult ? directFlows ? '第 ' + page + ' 页' : page + ' / ' + Math.max(1, Math.ceil(total / 20)) : '— / —' }}</span><button :disabled="(directFlows ? !flowNext : page * 20 >= total) || loading || saving || showingPrevious" @click="loadTable(page + 1)">下一页</button></footer>
    </section>
    <details v-if="batch && !sourceBlocked" class="source-disclosure">
      <summary>数据来源与更新<span v-if="batch.imported_at"> · {{ formatTime(batch.imported_at) }}</span></summary>
      <p>{{ batch.source?.data_origin === 'saas_database' ? 'SaaS数据库批次' : '已验收批次' }} · {{ batch.label }} · 设置版本 {{ batch.revision }} · {{ batch.can_edit ? '调整保留操作记录' : '当前为只读权限' }}</p>
      <p v-if="batch.automation_health">自动检查：{{ batch.automation_health.message }} · 最近检查 {{ batch.automation_health.checked_at ? formatTime(batch.automation_health.checked_at) : '暂无记录' }}。{{ batch.automation_health.recovery }}</p>
      <p v-if="batch.source?.database_scope" class="auto-summary">{{ batch.automation?.enabled === false ? '自动更新已关闭；当前展示已生成批次，需手动重新汇总。' : '后台每5分钟检查，仅自动更新本月和上月；历史账期保留原结果，需手动重新汇总。' }}<span v-if="batch.automation?.enabled !== false && batch.automation?.scope"> 自动范围：{{ batch.automation.scope.from }} 至 {{ batch.automation.scope.to }}，适用于全部汇总维度及流水明细。</span></p>
      <div v-if="batch.source?.database_scope" class="view-options"><span>已纳入：{{ batch.source.database_scope.from }} 至 {{ batch.source.database_scope.to }} · {{ batch.source.database_scope.stores.length }} 家店铺</span><button v-if="batch.can_edit" :disabled="loading || saving || rebuilding" @click="openCoverage">汇总范围</button><button v-if="batch.can_view_settings !== false" @click="openRebuildHistory">汇总记录</button><button v-if="dateWarning" :disabled="loading" @click="showUnresolvedDates">查看待补日期费用</button></div>
    </details>
    <details v-if="batch" class="reconciliation-disclosure" :open="attributionArea === 'pending'">
    <summary>归属核对<span> · {{ loading ? '核对中' : error ? '未获取' : (attribution.pending_rows || 0) + ' 条待归属' }}</span></summary>
    <section class="attribution-context" aria-label="费用归属">
      <div class="view-options"><button data-attribution="assigned" :aria-pressed="attributionArea === 'assigned'" :disabled="loading || saving" @click="changeAttribution('assigned')">已归属订单汇总</button><button data-attribution="pending" :aria-pressed="attributionArea === 'pending'" :disabled="loading || saving" @click="changeAttribution('pending')">待归属订单明细（{{ loading ? '核对中' : error ? '未获取' : (attribution.pending_rows || 0) + '条非零金额' }}）</button><span>{{ attributionArea === 'pending' ? '仅核对原额，不计入正式利润；参考项另行标记。' : '利润仅包含已归属订单的收支；不代表商品、成本和日期已全部核对。' }}</span></div>
      <details><summary>归属对账：参与汇总原额＝已归属订单＋待归属订单（{{ mode === 'operations' ? '运营' : '财务' }}口径）</summary><p class="detail-note">按当前账期、统计区间、国家、平台、店铺和币种核对，不随商品关键词及明细字段筛选缩小；不同币种不合计。未关联／未分摊的仓库处理费及仓库其他费不参与本次汇总，也不进入待核对，原登记保留不动。</p><div class="attribution-scroll"><table class="parts"><thead><tr><th>国家</th><th>科目</th><th>币种</th><th>参与汇总原额</th><th>已归属订单</th><th>待归属订单</th></tr></thead><tbody><tr v-for="item in attributionTotals" :key="item.country + item.currency + item.kind"><td>{{ item.country }}</td><td>{{ item.label }}</td><td>{{ item.currency }}</td><td>{{ money(item.total) }}</td><td>{{ money(item.assigned) }}</td><td>{{ money(item.pending) }}<small v-if="item.unknown_rows">另有{{ item.unknown_rows }}条金额未确认</small></td></tr></tbody></table></div><p v-for="item in attribution.item_gaps || []" :key="item.store" class="detail-note">{{ item.store }}：{{ item.orders }}个订单仍有商品归属待核，其中内部SKU待关联{{ item.sku_orders }}单、商品链接待关联{{ item.link_orders }}单；两项可能重叠，不认定分摊完成。</p></details>
    </section>
    </details>
    <details v-if="periodNote && (view !== 'detail' || !options.raw_flows)" class="calculation-disclosure"><summary>{{ appliedPeriodLabel }} · 计算口径</summary><p class="detail-note" role="note">{{ periodNote }}</p></details>



    </template>
    <el-drawer v-model="detailOpen" :title="detail?.title || (rateDetail ? '费率构成' : '金额构成')" size="min(850px, 95vw)" destroy-on-close>
      <p v-if="detailLoading" role="status">{{ detailStatus || '正在加载构成…' }}</p><el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <template v-if="detail"><p v-if="!rateDetail && detail.sales != null && !detail.cost">本行订单销售额：{{ money(detail.sales) }}；金额合计：{{ money(detail.amount) }}</p><p v-if="rateDetail">合计费率：{{ signedRate(detail.rate, detail.amount) }}</p><p class="detail-note">{{ detail.note }}</p>
        <FinanceCostDetail v-if="detail.cost && !rateDetail" :cost="detail.cost" :money="money" :loading="detailLoading" :can-back="!!detailQuery?.source_key" @drill="showSource" @page="changeCostPage" @flow-page="changeCostFlowPage" @back="readDetail(detailParams)" />
        <table v-if="detail.parts?.length" class="parts"><thead><tr><th>子项</th><th v-if="!rateDetail">金额</th><th>占本行销售额</th></tr></thead><tbody><tr v-for="(part, i) in detail.parts" :key="i"><td :style="{paddingLeft: ((part.level || 2) - 1) * 12 + 'px'}"><strong v-if="part.subtotal">{{ part.label }}</strong><template v-else>{{ part.label }}</template><small v-if="part.status === 'reference'">仅核对，不计入</small><small v-if="part.status === 'pending'">待核</small><small v-if="part.source && !rateDetail">{{ part.source }}</small></td><td v-if="!rateDetail" :class="sign(part.amount)">{{ money(part.amount) }}</td><td>{{ signedRate(part.rate, part.amount) }}</td></tr></tbody><tfoot><tr><th>合计（分类小计不重复计入）</th><td v-if="!rateDetail" :class="sign(detail.amount)">{{ money(detail.amount) }}</td><td>{{ signedRate(detail.rate, detail.amount) }}</td></tr></tfoot></table>
        <details v-if="detailRecordTotal && !rateDetail" class="source-records" @toggle="loadSourceRecords"><summary>来源明细（{{ detailRecordTotal }} 笔）</summary><table class="parts"><tbody><tr v-for="(record, i) in visibleDetailRecords" :key="record.key || i"><td>{{ record.date }}<small>{{ record.shop }} · {{ record.order }}</small></td><td>{{ record.description || record.source }}</td><td><button class="amount" @click="showSource(record.key)">{{ money(record.amount) }}</button></td></tr></tbody></table><div v-if="detailRecordPages > 1" class="pagination" role="group" aria-label="来源明细分页"><button :disabled="detailRecordPage <= 1" @click="changeRecordPage(detailRecordPage - 1)">上一页</button><span>{{ detailRecordPage }} / {{ detailRecordPages }}</span><button :disabled="detailRecordPage >= detailRecordPages" @click="changeRecordPage(detailRecordPage + 1)">下一页</button></div></details>
        <iframe v-if="detail.html && !rateDetail" :srcdoc="sourceDocument(detail.html)" title="原始金额来源" sandbox="" class="source-frame" />
      </template>
    </el-drawer>
    <el-dialog v-model="editorOpen" :title="operationLabel + '记录'" width="620px" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
      <form class="fee-form" @submit.prevent="submitFee"><p v-if="fee.kind === 'advertising' && !fee.id" class="full detail-note">此处仅登记明确的广告费用调整。充值本金、税率及扣款匹配请使用<button type="button" @click="editorOpen = false; openSettings('recharge')">广告充值／税费登记</button>。</p><label>店铺<select v-model="fee.store" :disabled="!!fee.id"><option v-for="shop in options.stores" :key="shop.id" :value="shop.id">{{ shop.code }}</option></select></label><label>账期<input v-model="fee.month" type="month" :disabled="!!fee.id" required /></label><label>日期<input v-model="fee.date" type="date" :disabled="!!fee.id" required /></label><label>计入科目<select v-model="fee.kind" :disabled="!!fee.id"><option v-for="k in (fee.id ? options.kinds : options.editable_kinds || options.kinds)" :key="k.key" :value="k.key">{{ !fee.id && k.key === 'advertising' ? '广告费用调整（非充值）' : k.label }}</option></select></label><label>口径<select v-model="fee.mode" :disabled="!!fee.id || fee.kind !== 'advertising'"><option value="both" :disabled="fee.kind === 'advertising'">双口径</option><option value="operations">运营</option><option value="finance">财务</option></select></label><label>订单号<input v-model="fee.order" :disabled="!!fee.id || fee.kind === 'advertising'" placeholder="留空为店铺公共费用" /></label><label>金额（{{ feeCurrency }}；收入为正，支出为负）<input v-model="fee.amount" inputmode="decimal" :disabled="fee.operation !== 'save'" required /></label><label class="full">变更原因<textarea v-model="fee.reason" required maxlength="1000" /></label><p v-if="feeClosed" class="full detail-note" role="alert">该店铺账期已关账，请在开放账期登记调整。</p><el-alert v-if="feeError" class="full" :title="feeError" type="error" :closable="false" /><div class="full actions"><button type="button" :disabled="saving" @click="editorOpen = false">取消</button><button type="submit" :disabled="saving || feeClosed || showingPrevious">{{ saving ? '正在校验保存…' : operationLabel + '并更新汇总' }}</button></div></form>
    </el-dialog>
    <el-drawer v-model="historyOpen" title="费用操作记录" size="min(850px, 95vw)" destroy-on-close><p v-if="historyLoading" role="status">{{ historyStatus || '正在加载操作记录…' }}</p><p v-if="historyError">{{ historyError }}</p><table class="parts"><thead><tr><th>时间／操作人／操作</th><th>归属、来源与变更</th><th>原因</th></tr></thead><tbody><tr v-for="(item, index) in history.rows" :key="index"><td>{{ formatTime(item.at) }}<small>{{ item.actor?.name || '旧记录未登记操作人' }}{{ item.revision ? ' · 版本 ' + item.revision : '' }}</small><small>{{ {save:'保存',disable:'禁用',restore:'恢复',delete:'删除',exclude_source:'排除汇总',restore_source:'恢复汇总'}[item.operation] }}</small></td><td>{{ options.stores.find(s => s.id === item.after?.store)?.code || item.after?.store }} · {{ item.after?.month }}<small>{{ options.kinds.find(k => k.key === item.after?.kind)?.label || item.after?.kind }} · {{ money(item.after?.amount) }} {{ item.after?.currency }}</small><small>来源：{{ item.after?.id }}</small><small v-if="['exclude_source','restore_source'].includes(item.operation)">{{ item.before?.excluded ? '已排除' : '参与汇总' }} → {{ item.after?.excluded ? '已排除' : '参与汇总' }}</small><small v-else>金额：{{ money(item.before?.amount) }} → {{ money(item.after?.amount) }}；状态：{{ item.before?.state || '未登记' }} → {{ item.after?.state }}</small></td><td>{{ item.after?.reason }}</td></tr></tbody></table><p v-if="!historyLoading && !historyError && !history.rows.length">暂无费用操作记录。</p><button :disabled="historyLoading || history.page <= 1" @click="showHistory(history.page - 1)">上一页</button><span> {{ history.page }} / {{ Math.max(1, Math.ceil(history.total / 20)) }} </span><button :disabled="historyLoading || history.page * 20 >= history.total" @click="showHistory(history.page + 1)">下一页</button></el-drawer>
    <el-dialog v-model="advanced" title="广告及账务设置" width="min(1180px, 96vw)" top="3vh" destroy-on-close @closed="refresh"><FinanceSummary v-if="advanced" tools-only :initial-context="legacyContext" /></el-dialog>
    <el-dialog v-model="coverageOpen" title="汇总范围" width="min(620px,95vw)" :close-on-click-modal="false">
      <p>重新汇总读取当前范围内的 SaaS 数据。纳入新月份或店铺时，请在此扩大范围；保留已有账期和店铺。不会补采平台数据。</p>
      <form class="fee-form" @submit.prevent="confirmCoverage"><label>开始日期<input v-model="coverage.from" type="date" required /></label><label>结束日期<input v-model="coverage.to" type="date" required /></label><fieldset class="full coverage-stores"><legend>店铺（已选 {{ coverage.stores.length }} 家）</legend><label v-for="shop in batch?.scope_stores || []" :key="shop.id"><input v-model="coverage.stores" type="checkbox" :value="shop.id" />{{ shop.code }}</label></fieldset><p class="full">新结果通过校验后才替换当前批次；原批次保留用于追溯。</p><div class="full actions"><button type="button" @click="coverageOpen = false">取消</button><button type="submit" :disabled="rebuilding || !coverage.stores.length">按此范围重新汇总</button></div></form>
    </el-dialog>
    <el-dialog v-model="rebuildHistoryOpen" title="汇总记录" width="min(850px,95vw)"><p>仅展示本租户最近 10 次任务，失败任务不会替换已通过校验的批次。</p><p v-if="rebuildHistoryLoading" role="status">正在读取最新汇总记录…</p><p v-if="rebuildHistoryError" role="alert">{{ rebuildHistoryError }}</p><table class="parts"><thead><tr><th>提交时间</th><th>来源 → 结果批次</th><th>状态</th><th>完成时间</th></tr></thead><tbody><tr v-for="job in batch?.rebuild_history || []" :key="job.id"><td>{{ formatTime(job.created_at) }}</td><td>{{ job.dataset_id }} → {{ job.result_dataset_id || '—' }}</td><td>{{ jobLabel(job.status) }}</td><td>{{ formatTime(job.finished_at) }}</td></tr></tbody></table><p v-if="!batch?.rebuild_history?.length">暂无汇总任务记录。</p></el-dialog>
  </section>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { fetchFinanceSummary, fetchFinanceSummaryJob, rebuildFinanceSummary, fetchFinanceSummaryTable, fetchFinanceSummaryDetail, saveFinanceSummaryFee, fetchFinanceSummaryHistory, fetchFinanceSourceFlows, fetchFinanceSourceFlowDetail } from '../../api/financeReconciliation';
import FinanceCostDetail from './FinanceCostDetail.vue';
import FinancePeriodPicker from './FinancePeriodPicker.vue';
import { calendarDays, periodRange, periodText } from './financePeriods';
const initialization=ref(null);
const queryContext=ref(null);let refreshRequested=false;
const FinanceSummary = defineAsyncComponent(() => import('./FinanceSummary.vue'));
const views = [['country','国家汇总'],['store','店铺汇总'],['order','订单汇总'],['sku','SKU汇总'],['product_link','商品链接汇总'],['detail','流水明细']];
const amountColumns = [['sales','订单销售额'],['refund','订单退款'],['order_fee','订单费用'],['adjustment','订单调整'],['shop_adjustment','店铺调整'],['operations','运营口径广告花费'],['finance','财务口径广告花费'],['product_cost','商品成本'],['gcash','GCash退款'],['promotion','刷单费用'],['warehouse_order','仓库处理费'],['warehouse_other','仓库其他处理费']].map(([key,label])=>({key,label}));
const blank = () => ({month:'',period_type:'month',period:'',country:'',platform:'',store:'',currency:'',order:'',sku:'',product:'',from:'',to:'',kind:'',keyword:'',status:'',editable:''});
const batch=ref(null),rows=ref([]),options=ref({stores:[],countries:{},months:[],kinds:[]}),view=ref('store'),mode=ref('operations'),scope=ref('store'),page=ref(1),total=ref(0),loading=ref(false),saving=ref(false),rebuilding=ref(false),error=ref(''),tableBox=ref(null),advanced=ref(false);
const flowMode=ref('source');
const directFlows=computed(()=>view.value==='detail' && attributionArea.value==='assigned' && (!batch.value || flowMode.value==='source'));
const flowNext=ref(false);let flowCursors=[null];
const attributionArea=ref('assigned'),attribution=ref({totals:[],pending_rows:0,item_gaps:[]});let assignedView='store';
const summaryTotals=ref([]),displayedResult=ref(null),previousResult=ref(false);let displayedSignature='';
const attributionTotals=computed(()=>attribution.value.totals.filter(item=>item.mode===mode.value));
const draft=reactive(blank());let applied=blank(),requestVersion=0,alive=true,defaultMonthPending=true;const tabMemory={};
const sourceBlocked=computed(()=>batch.value?.source_available===false);
const coverageOpen=ref(false),rebuildHistoryOpen=ref(false),coverage=reactive({from:'',to:'',stores:[]});
const formatTime=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
const jobLabel=value=>({queued:'等待执行',running:'计算中',ready:'已完成',failed:'失败，原批次保留',blocked:'权限已变化',superseded:'已被新版本替代'}[value]||value);
function openCoverage(){Object.assign(coverage,{...batch.value.source.database_scope,stores:[...batch.value.source.database_scope.stores]});coverageOpen.value=true;}
async function confirmCoverage(){const scope={...coverage,stores:[...coverage.stores]};coverageOpen.value=false;await rebuild(false,scope);}
async function showUnresolvedDates(){
  flowMode.value='summary';
  attributionArea.value='assigned';view.value='detail';
  Object.assign(draft,blank(),{month:applied.month,period_type:applied.period_type,period:applied.period,country:applied.country,platform:applied.platform,store:applied.store,currency:applied.currency,kind:'warehouse_order',status:'pending'});
  applied={...draft};await loadTable(1,true);
}

const autoError=ref('');let autoTimer,checking=false;
const dateWarning=ref(''),periodNote=ref('');
const availablePeriods=computed(()=>{
 if(!draft.month||draft.period_type==='month')return [];
 const dates=draft.period_type==='half_month'?[draft.month+'-01',draft.month+'-16']:calendarDays(draft.month).filter(day=>day.startsWith(draft.month));
 return [...new Set(dates.map(day=>periodRange(draft.period_type,day).from))].sort().reverse().map(value=>({value,...periodRange(draft.period_type,value)}));
});
const appliedPeriodLabel=ref('月度分摊');
function normalizePeriod(){if(draft.period_type==='month'){draft.period='';return;}if(!draft.month)draft.month=options.value.months[0]||batch.value?.source?.database_scope?.to?.slice(0,7)||'';if(draft.period!=='undated'&&!availablePeriods.value.some(r=>r.value===draft.period)){const today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'}),end=batch.value?.source?.database_scope?.to,cap=end&&end<today?end:today;draft.period=availablePeriods.value.find(r=>r.value<=cap)?.value||'undated';}}
function periodLabel(filters){const type=filters.period_type||'month',name=({week:'周度分摊',half_month:'半月分摊',month:'月度分摊'})[type];return name+' · '+(filters.month||'全部账期')+(type==='month'?'':' · '+periodText(filters));}
const queryStatus=ref(''),detailStatus=ref(''),rebuildStatus=ref('');const pollWaiters=new Set();
const readControllers=new Map();
function stopRead(key){readControllers.get(key)?.abort();readControllers.delete(key);}
function startRead(key){stopRead(key);const controller=new AbortController();readControllers.set(key,controller);return controller.signal;}
function waitForPoll(delay,current,{signal,backoff=false}={}){return new Promise(resolve=>{
 let timer=null;const deadline=Date.now()+delay;
 const finish=()=>{window.clearTimeout(timer);document.removeEventListener('visibilitychange',visibility);signal?.removeEventListener('abort',finish);pollWaiters.delete(finish);resolve();};
 const visibility=()=>{if(document.hidden){window.clearTimeout(timer);timer=null;}else if(backoff)timer=window.setTimeout(finish,Math.max(0,deadline-Date.now()));else finish();};
 finish.current=current;pollWaiters.add(finish);document.addEventListener('visibilitychange',visibility);signal?.addEventListener('abort',finish,{once:true});
 if(signal?.aborted||!current())finish();else if(!document.hidden)timer=window.setTimeout(finish,delay);
});}
function cancelInactivePolls(){for(const finish of pollWaiters)if(!finish.current())finish();}
async function calculation(response,current,status,readOnly=true,signal){
  if(!current())throw Error('查询已取消');
  let data=result(response);const started=Date.now();let polls=0;
  while(data?.job){
    if(!current())throw Error('查询已取消');
    if(data.job.status==='ready')return data.result;
    if(data.job.error_code==='SOURCE_READ_TIMEOUT')throw Error('来源读取超出安全时限，请缩小店铺或账期后重新查询；账务数据未更改。');
    if(data.job.error_code==='BROKER_UNAVAILABLE')throw Error('后台任务服务暂不可用，原结果未更改；请稍后重新检查。');
    if(Date.now()-started>900000)throw Error('等待已超过15分钟，已停止本页轮询；后台任务未被取消，请查看汇总记录后重新检查。');
    if(!data.pending){const failure=Error(data.job.error_code==='CALCULATOR_TIMEOUT'?'财务计算超过120秒，原结果保持不变，请重新查询。':({superseded:'来源或设置版本已变化，请刷新批次后重试。',blocked:'权限已变化，请重新登录并核对访问权限。',expired:'查询缓存已过期，请重新查询当前批次。',failed:'后台计算失败，原批次保持不变，请重试。'})[data.job.status]||'计算未完成，请重试。');failure.code=data.job.status;throw failure;}
    if(status)status.value=data.job.error_code==='CALCULATOR_BUSY'?'计算资源正忙，任务将在后台自动重试…':data.job.phase==='merging'?'正在合并近期变更，等待汇总窗口…':data.job.status==='queued'?'后台任务排队中，等待计算资源…':'后台正在计算并校验，完成后自动更新…';
    if(status)status.value+=' 已等待 '+Math.floor((Date.now()-started)/1000)+' 秒';
    const normalDelay=data.job.status==='queued'?5000:1500;
    const waiting=['merging','retrying'].includes(data.job.phase)||data.job.error_code==='CALCULATOR_BUSY';
    const delay=readOnly&&!waiting?Math.min([300,750,1500,3000,5000][Math.min(polls,4)],normalDelay):normalDelay;
    await waitForPoll(delay,current,{signal});polls++;
    if(!current())throw Error('查询已取消');
    for(let retry=0;;retry++){
      if(!current())throw Error('查询已取消');
      let response;
      try{response=await (signal?fetchFinanceSummaryJob(data.job.id,{signal}):fetchFinanceSummaryJob(data.job.id));}
      catch(e){
        const http_status=e.response?.status;
        if(![502,503].includes(http_status)&&!['ERR_NETWORK','ECONNABORTED','ETIMEDOUT'].includes(e.code))throw e;
        response={success:false,http_status,code:http_status?'HTTP_'+http_status:'HTTP_NETWORK_ERROR',message:e.message};
      }
      if(!current())throw Error('查询已取消');
      const temporary=response?.success===false&&([502,503].includes(response.http_status)||response.code==='HTTP_NETWORK_ERROR');
      if(!temporary||retry>=3){data=result(response);break;}
      if(status)status.value='结果读取暂时失败，正在自动重试（'+(retry+1)+'/3）；后台计算继续。';
      await waitForPoll(1000*2**retry,current,{signal,backoff:true});
    }
  }
  return data;
}
const availableStores=computed(()=>options.value.stores.filter(s=>(!draft.country||s.country===draft.country)&&(!draft.platform||s.platform===draft.platform)));
const currencies=computed(()=>[...new Set(options.value.stores.map(s=>s.currency).filter(Boolean).concat(view.value === 'detail' ? options.value.currencies || ['CNY'] : []))]);
const identityColumns=computed(()=>{const cols=[{key:'country',label:'国家'}];if(view.value!=='country')cols.push({key:'platform',label:'平台'},{key:'shop',label:'店铺'});if(view.value==='order')cols.push({key:'order',label:'订单号'});if(view.value==='sku')cols.push({key:'sku',label:'商品／SKU'});if(view.value==='product_link')cols.push({key:'title',label:'商品链接／商品ID'},{key:'sku_count',label:'SKU数'});cols.push({key:'currency',label:'币种'});let left=0;return cols.map(col=>{const width={country:90,platform:90,shop:105,order:185,sku:260,title:280,sku_count:70,currency:70}[col.key];const result={...col,width,left};left+=width;return result;});});
const metricDisplay=ref('amount');
const displayRates=[['gross_margin','毛利'],['profit_operations','运营利润'],['profit_finance','财务利润']];
const metricLabel=([key,label])=>metricDisplay.value==='percentage'?({gross_margin:'毛利率',profit_operations:'运营利润率',profit_finance:'财务利润率'}[key]||label):label;
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
function signedRate(rate,value){if(value==null||!rate||!/^[-+]?\d+(?:\.\d+)?%$/.test(rate))return '—';return rate.replace(/^\+/,'');}
function anomalyText(row,key,isRate=false){
  const label=amountColumns.find(c=>c.key===key)?.label||({gross_margin:'毛利',profit_operations:'运营利润',profit_finance:'财务利润'})[key]||key;
  const reasons=[...(row.field_issues?.[key]||[])];
  if(!reasons.length&&row.partial?.[key])reasons.push('来源或汇率不完整，当前为已知部分');
  if(isRate){
    reasons.push(...(row.field_issues?.sales||[]).map(reason=>'费率分母：'+reason));
    if(row.values.sales!=null&&Number(row.values.sales)===0)reasons.push('销售额为零，费率按 0.00% 展示，不影响金额及利润计算');
  }
  return reasons.length?label+'：'+[...new Set(reasons)].join('；'):'';
}
const tableWidth=computed(()=>identityColumns.value.reduce((sum,c)=>sum+c.width,0)+12*132+90+displayRates.length*150);
const settingsKind=ref('');
function openSettings(kind=''){if(showingPrevious.value)return;settingsKind.value=kind;advanced.value=true;}
const legacyContext=computed(()=>({toolKind:settingsKind.value,view:view.value,mode:mode.value,page:page.value,fields:{...applied},skuScope:scope.value}));
function identity(row,key){return key==='platform'?({lazada:'Lazada',shopee:'Shopee'}[row.identity[key]]||row.identity[key]||'—'):row.identity[key]??'—';}
function money(value,missing='—') {if(value==null)return missing;const text=String(value),negative=text.startsWith('-'),[whole,fraction='']=text.replace(/^[+-]/,'').split('.');let cents=BigInt(whole||'0')*100n+BigInt((fraction+'00').slice(0,2));if(Number(fraction[2]||0)>=5)cents++;const units=(cents/100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g,',');return(negative&&cents!==0n?'-':'')+units+'.'+(cents%100n).toString().padStart(2,'0');}
function conversionText(row){const c=row.conversion;return c.missing?'缺少 '+c.from+' → '+c.to+' 的有效汇率，折算金额待核':c.from+' → '+c.to+'；汇率 '+(c.rate??'待核')+'；'+c.basis+'；'+c.period+(c.input_id?'；依据 #'+c.input_id:'');}
const sign=value=>value==null?'unknown':Number(value)<0?'negative':Number(value)>0?'positive':'';
const safeUrl=value=>typeof value==='string'&&/^https:\/\/(?:www\.)?(?:lazada\.(?:com\.ph|co\.th|com\.my|sg|co\.id|vn)|shopee\.(?:ph|co\.th|com\.my|sg|co\.id|vn))\//i.test(value);
function params(number=page.value){return{view:view.value,mode:mode.value,scope:scope.value,page:number,page_size:20,filter_attribution:attributionArea.value,...Object.fromEntries(Object.entries(applied).map(([k,v])=>['filter_'+k,v]))};}
function sourceParams(){
 let range;
 if(applied.period && applied.period!=='undated')range=periodRange(applied.period_type,applied.period);
 else if(applied.month)range=periodRange('month',applied.month);
 else throw Error('请选择统计周期；原始流水不执行无日期范围的查询。');
 const filters=Object.fromEntries(['country','platform','store','currency','kind','order','keyword'].filter(k=>applied[k]).map(k=>[k,applied[k]]));
 const status={normal:'confirmed',pending:'pending',reference:'reference'}[applied.status];if(status)filters.status=status;
 return{start:applied.from&&applied.from>range.from?applied.from:range.from,end:applied.to&&applied.to<range.to?applied.to:range.to,
  period_type:applied.period_type,undated:applied.period==='undated',page_size:50,...filters};
}
async function loadSourceTable(number=1,resetPosition=false){
 if(resetPosition || number===1){flowCursors=[null];number=1;}
 if(number>1&&!flowCursors[number-1])return;
 stopRead('table');const signal=startRead('table'),version=++requestVersion;
 clearResult();loading.value=true;error.value='';queryStatus.value='正在读取原始流水…';flowNext.value=false;
 try{
  const params=sourceParams();if(flowCursors[number-1])params.cursor=flowCursors[number-1];
  const response=await fetchFinanceSourceFlows(params,{signal});
  if(!alive||version!==requestVersion||!directFlows.value)return;
  const data=result(response);
  rows.value=data.rows;options.value=data.options;page.value=number;
  displayedResult.value={source_flows:true,tenant_id:data.tenant_id,access_signature:data.access_signature};
  flowNext.value=!!data.has_more;flowCursors[number]=data.next_cursor;flowCursors.length=number+1;
  appliedPeriodLabel.value=periodLabel(applied);dateWarning.value=data.period_warning||'';periodNote.value='';
  if(resetPosition&&tableBox.value){tableBox.value.scrollTop=0;tableBox.value.scrollLeft=0;}
 }catch(e){if(alive&&version===requestVersion){if(accessFailure(e))forgetPrivateData();error.value=e.message;}}
 finally{if(alive&&version===requestVersion)loading.value=false;}
}
function changeFlowMode(value){if(loading.value||saving.value||value===flowMode.value)return;flowMode.value=value;clearResult();loadTable(1,true);}
async function readSourceDetail(row){
 const [source,id]=row.source_id.split(':'),signal=startRead('detail'),version=++detailRequest;
 detailQuery.value={source_key:row.source_id};detailOpen.value=true;detail.value=null;detailError.value='';detailLoading.value=true;
 try{const response=await fetchFinanceSourceFlowDetail(source,id,{signal});if(!alive||!detailOpen.value||version!==detailRequest)return;detail.value=result(response);}
 catch(e){if(alive&&detailOpen.value&&version===detailRequest)detailError.value=e.message;}
 finally{if(alive&&version===detailRequest)detailLoading.value=false;}
}
function resultSignature(number){return JSON.stringify([view.value,mode.value,scope.value,attributionArea.value,number,applied]);}
function compatibleBatch(next){const old=displayedResult.value;if(!old)return false;if(old.access_signature!==next?.access_signature)return false;return old.tenant_id!=null&&next?.tenant_id!=null?String(old.tenant_id)===String(next.tenant_id):old.dataset===next?.dataset;}
function clearResult(){queryContext.value=null;rows.value=[];summaryTotals.value=[];total.value=0;attribution.value={totals:[],pending_rows:0,item_gaps:[]};displayedResult.value=null;displayedSignature='';previousResult.value=false;}
function forgetPrivateData(){for(const key of readControllers.keys())stopRead(key);clearResult();options.value={stores:[],countries:{},months:[],kinds:[]};detail.value=null;detailOpen.value=false;detailRequest++;history.value={rows:[],total:0,page:1};historyOpen.value=false;historyRequest++;editorOpen.value=false;fee.value={};advanced.value=false;batch.value=null;initialization.value=null;queryContext.value=null;}
function clearAccessScope(){forgetPrivateData();Object.assign(draft,blank());applied={...draft};page.value=1;defaultMonthPending=true;for(const key of Object.keys(tabMemory))delete tabMemory[key];}
function replaceBatch(next){if(displayedResult.value&&!compatibleBatch(next)){clearAccessScope();if(/^\d{4}-\d{2}-\d{2}$/.test(next.source?.database_scope?.to||'')){draft.month=next.source.database_scope.to.slice(0,7);applied={...draft};}}batch.value=next;}
function accessFailure(e){return e.http_status===401||e.http_status===403||e.code==='blocked'||/权限|登录|租户/.test(e.message||'');}
const showingPrevious=computed(()=>!!displayedResult.value&&(loading.value||rebuilding.value||previousResult.value));
const backgroundRefresh=computed(()=>['queued','running'].includes(batch.value?.refresh_job?.status));
const backgroundFailed=computed(()=>['failed','blocked'].includes(batch.value?.refresh_job?.status));
function result(response){if(!response?.success){const failure=Error(response?.message||'请求未完成，请重试');failure.http_status=response?.http_status;failure.code=response?.code;if(accessFailure(failure)){forgetPrivateData();dateWarning.value='';periodNote.value='';}throw failure;}return response.data;}
async function readMetadata(params,current,key='metadata'){const signal=startRead(key);const response=await fetchFinanceSummary(params,{signal});if(signal.aborted||!current())throw Object.assign(Error('查询已取消'),{code:'REQUEST_CANCELED'});return result(response);}
async function refresh(){stopRead('table');stopRead('table-metadata');const version=++requestVersion;loading.value=true;error.value='';try{const data=await readMetadata({native:1,direct:1},()=>alive&&version===requestVersion);if(!alive||version!==requestVersion)return;if(data.direct_query){replaceBatch(data);initialization.value=null;options.value.stores=(data.scope_stores||[]).map(shop=>({...shop,id:String(shop.id),country:shop.country_code,platform:shop.platform__platform_type}));options.value.countries=Object.fromEntries(options.value.stores.map(shop=>[shop.country_code,shop.country_code]));if(!draft.month){draft.month=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'}).slice(0,7);applied={...draft};}await loadTable(1,true);return;}if(data.initialized===false){forgetPrivateData();initialization.value=data;options.value.stores=(data.scope_stores||[]).map(shop=>({...shop,id:String(shop.id)}));if(!draft.month){draft.month=data.initialization_job?.scope?.to?.slice(0,7)||new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'}).slice(0,7);applied={...draft};}appliedPeriodLabel.value=periodLabel(applied);loading.value=false;if(directFlows.value)await loadSourceTable(1,true);return;}initialization.value=null;if(!batch.value && /^\d{4}-\d{2}-\d{2}$/.test(data.source?.database_scope?.to||'')){draft.month=data.source.database_scope.to.slice(0,7);applied={...draft};}replaceBatch(data);autoError.value='';if(sourceBlocked.value){clearResult();loading.value=false;return;}await loadTable(page.value);await rebuildIfChanged();}catch(e){if(alive&&version===requestVersion){forgetPrivateData();error.value=e.message;loading.value=false;}}}
async function refreshCurrent(){if(batch.value?.direct_query){refreshRequested=true;await loadTable(page.value,true);}else await refresh();}
async function rebuild(automatic=false,scopeOverride=null){if(loading.value||saving.value||rebuilding.value||!batch.value||sourceBlocked.value)return;rebuilding.value=true;rebuildStatus.value='正在读取SaaS数据并提交后台汇总…';error.value='';autoError.value='';try{const data=await calculation(await (scopeOverride ? rebuildFinanceSummary(batch.value.dataset,batch.value.revision,scopeOverride) : rebuildFinanceSummary(batch.value.dataset,batch.value.revision)),()=>alive,rebuildStatus,false);if(!alive)return;replaceBatch(data);await loadTable(automatic?page.value:1,!automatic);}catch(e){if(alive){if(e.code==='superseded'){await refresh();return;}if(automatic)autoError.value='自动汇总未完成，保留原结果，稍后重试：'+e.message;else error.value=e.message;}}finally{if(alive)rebuilding.value=false;}}
function autoIdle(){return !directFlows.value&&!hasDraftChanges()&&alive&&!document.hidden&&!loading.value&&!saving.value&&!rebuilding.value&&!advanced.value&&!editorOpen.value&&!detailOpen.value&&!historyOpen.value&&!coverageOpen.value&&!rebuildHistoryOpen.value;}
async function rebuildIfChanged(){if(batch.value?.automation?.mode!=='server'&&autoIdle()&&!sourceBlocked.value&&batch.value?.can_edit&&batch.value?.source?.database_scope&&batch.value.source_changed)await rebuild(true);}
const rebuildHistoryLoading=ref(false),rebuildHistoryError=ref('');let rebuildHistoryRequest=0;
watch(rebuildHistoryOpen,open=>{if(!open){stopRead('rebuild-history');rebuildHistoryRequest++;rebuildHistoryLoading.value=false;rebuildHistoryError.value='';}},{flush:'sync'});
async function openRebuildHistory(){
 rebuildHistoryOpen.value=true;const version=++rebuildHistoryRequest,tableVersion=requestVersion;rebuildHistoryLoading.value=true;rebuildHistoryError.value='';
 try{const data=await readMetadata({native:1},()=>alive&&rebuildHistoryOpen.value&&version===rebuildHistoryRequest&&tableVersion===requestVersion,'rebuild-history');const changed=data.dataset!==batch.value?.dataset||data.revision!==batch.value?.revision;replaceBatch(data);if(changed)await loadTable(page.value);}
 catch(e){if(alive&&rebuildHistoryOpen.value&&version===rebuildHistoryRequest&&tableVersion===requestVersion)rebuildHistoryError.value=e.message;}finally{if(alive&&version===rebuildHistoryRequest)rebuildHistoryLoading.value=false;}
}
async function checkForChanges(){
  if(checking||!autoIdle()||batch.value?.direct_query||!batch.value?.source?.database_scope)return;
  checking=true;const version=requestVersion;
  try{
    let data=await readMetadata({native:1,status:1},()=>autoIdle()&&version===requestVersion);
    if(!autoIdle()||version!==requestVersion)return;
    const changed=sourceBlocked.value||data.dataset!==batch.value.dataset||data.revision!==batch.value.revision||String(data.tenant_id)!==String(batch.value.tenant_id)||data.access_signature!==batch.value.access_signature;
    if(data.lightweight){
      if(changed){if(data.access_signature!==batch.value.access_signature)clearAccessScope();data=await readMetadata({native:1},()=>autoIdle()&&version===requestVersion);if(!autoIdle()||version!==requestVersion)return;}
      else{batch.value={...batch.value,automation_health:data.automation_health,can_edit:data.can_edit,source_available:data.source_available,refresh_job:data.refresh_job,automation:{...batch.value.automation,enabled:data.automatic_update_enabled}};autoError.value='';return;}
    }
    replaceBatch(data);autoError.value='';
    if(sourceBlocked.value)return;
    if(changed)await loadTable(page.value);
    await rebuildIfChanged();
  }catch(e){if(e.code!=='REQUEST_CANCELED'&&autoIdle()&&version===requestVersion)autoError.value='自动检测暂未完成，稍后重试：'+e.message;}
  finally{checking=false;}
}
let pendingTableWait=null;
function cancelTableWait(){const wait=pendingTableWait;pendingTableWait=null;if(wait){window.clearTimeout(wait.timer);wait.resolve();}}
async function loadTable(number=1,resetPosition=false,coalesce=false){if(directFlows.value){if(!batch.value&&!initialization.value)return;await loadSourceTable(number,resetPosition);return;}if(!batch.value){if(readControllers.has('table')){stopRead('table');cancelTableWait();requestVersion++;clearResult();loading.value=false;flowNext.value=false;}return;}stopRead('metadata');stopRead('table-metadata');const context=queryContext.value;const signal=startRead('table');cancelTableWait();let keep=!!displayedResult.value&&compatibleBatch(batch.value)&&displayedSignature===resultSignature(number);if(!keep)clearResult();previousResult.value=keep;const version=++requestVersion;loading.value=true;queryStatus.value='';page.value=number;error.value='';if(!keep){dateWarning.value='';periodNote.value='';}try{let data;
appliedPeriodLabel.value=periodLabel(applied,options.value);
if(coalesce){await new Promise(resolve=>{pendingTableWait={resolve,timer:window.setTimeout(()=>{pendingTableWait=null;resolve();},200)};});if(!alive||version!==requestVersion)return;}
for(let attempt=0;attempt<2;attempt++){
  appliedPeriodLabel.value=periodLabel(applied,options.value);
  try{data=await calculation(await fetchFinanceSummaryTable(batch.value.dataset,{...params(number),...(refreshRequested?{refresh:1}:batch.value.direct_query&&context?{query_context:context}:{})},{signal}),()=>alive&&version===requestVersion,queryStatus,true,signal);break;}
  catch(e){
    if(e.code!=='superseded'||attempt||!alive||version!==requestVersion)throw e;
    queryStatus.value='批次已更新，正在读取最新汇总…';
    const latest=await readMetadata({native:1,...(batch.value?.direct_query?{direct:1}:{})},()=>alive&&version===requestVersion,'table-metadata');
    if(!alive||version!==requestVersion)return;
    replaceBatch(latest);if(keep&&(!compatibleBatch(latest)||displayedSignature!==resultSignature(number))){clearResult();keep=false;}
    if(sourceBlocked.value){clearResult();return;}
  }
}
if(!alive||version!==requestVersion)return;queryContext.value=data.query_context||null;refreshRequested=false;if(defaultMonthPending){defaultMonthPending=false;if(!applied.month&&data.options.months.length){options.value=data.options;draft.month=[...data.options.months].sort().reverse()[0];applied={...draft};await loadTable(1,true);return;}}rows.value=data.rows;displayedResult.value={dataset:batch.value.dataset,tenant_id:batch.value.tenant_id,access_signature:batch.value.access_signature,revision:data.revision,imported_at:batch.value.imported_at,source_read_at:data.source_read_at};displayedSignature=resultSignature(data.page);previousResult.value=false;summaryTotals.value=data.summary_totals||[];attribution.value=data.attribution||{totals:[],pending_rows:0,item_gaps:[]};dateWarning.value=[data.period_warning,data.date_warning].filter(Boolean).join(' ');periodNote.value=data.period_note||'';appliedPeriodLabel.value=periodLabel(applied,data.options);total.value=data.total;page.value=data.page;options.value=data.options;batch.value.revision=data.revision;await nextTick();if(resetPosition&&tableBox.value){tableBox.value.scrollTop=0;tableBox.value.scrollLeft=0;}}catch(e){if(alive&&version===requestVersion){if(accessFailure(e))forgetPrivateData();else if(!keep)clearResult();else previousResult.value=!!displayedResult.value;error.value=e.message;}}finally{if(alive&&version===requestVersion)loading.value=false;}}
function hasDraftChanges(){return Object.keys(draft).some(key=>draft[key]!==applied[key]);}
function search(){if(saving.value||rebuilding.value)return;normalizePeriod();applied={...draft};loadTable(1,true);}
function setPeriod(value){Object.assign(draft,value);}
function reset(){const period={month:applied.month,period_type:applied.period_type,period:applied.period};Object.assign(draft,blank(),period);search();}
function changeAttribution(value){if(value===attributionArea.value||loading.value||saving.value)return;attributionArea.value=value;rows.value=[];total.value=0;if(value==='pending'){assignedView=view.value;delete tabMemory.detail;if(view.value!=='detail'){changeView('detail',true);return;}const common=Object.fromEntries(['month','period_type','period','country','platform','store','currency'].map(k=>[k,applied[k]]));Object.assign(draft,blank(),common);applied={...draft};}else if(view.value!==assignedView){changeView(assignedView);return;}loadTable(1,true);}
function changeView(value,keepAttribution=false){if(value===view.value||saving.value)return;if(!keepAttribution)attributionArea.value='assigned';tabMemory[view.value]={draft:{...draft},applied:{...applied}};const common=Object.fromEntries(['month','period_type','period','country','platform','store','currency'].map(k=>[k,applied[k]]));view.value=value;rows.value=[];const saved=tabMemory[value];Object.assign(draft,{...blank(),...saved?.draft,...common});applied={...draft,...saved?.applied,...common};loadTable(1,true,loading.value);}
const detailOpen=ref(false),detail=ref(null),detailLoading=ref(false),detailError=ref(''),detailQuery=ref(null);let detailRequest=0,detailParams=null;
const rateDetail=computed(()=>String(detailQuery.value?.kind||'').startsWith('rate:'));
const legacyRecordPage=ref(1),detailRecordTotal=computed(()=>detail.value?.records_total??detail.value?.records?.length??0);
const detailRecordPage=computed(()=>detail.value?.records_page||legacyRecordPage.value),detailRecordPages=computed(()=>Math.max(1,Math.ceil(detailRecordTotal.value/(detail.value?.records_page_size||50))));
const visibleDetailRecords=computed(()=>detail.value?.records_page_size?detail.value.records:(detail.value?.records||[]).slice((legacyRecordPage.value-1)*50,legacyRecordPage.value*50));
watch(detail,()=>{legacyRecordPage.value=1;},{flush:'sync'});
function changeRecordPage(number){if(detail.value?.records_page_size)changeCostFlowPage(number);else legacyRecordPage.value=number;}

watch(detailOpen,open=>{if(!open){stopRead('detail');detailRequest++;detail.value=null;detailLoading.value=false;detailError.value='';detailStatus.value='';cancelInactivePolls();}},{flush:'sync'});
async function showDetail(row,kind){if(showingPrevious.value)return;if(directFlows.value){await readSourceDetail(row);return;}detailParams={...params(),row_key:row.key,kind};await readDetail(detailParams);}
async function showSource(key){await readDetail({...detailParams,source_key:key,cost_page:1});}
function changeCostFlowPage(number){readDetail({...detailQuery.value,flow_page:number});}
function changeCostPage(number){const query={...detailQuery.value,cost_page:number};if(!query.source_key)detailParams=query;readDetail(query);}
function loadSourceRecords(event){if(event.target.open && !detailLoading.value && !detail.value?.records?.length && detail.value?.records_total)readDetail(detailQuery.value,true);}
async function readDetail(query,includeRecords=false){query={flow_page:1,...query};const signal=startRead('detail');const version=++detailRequest;detailQuery.value=query;detailOpen.value=true;if(!includeRecords)detail.value=null;detailError.value='';detailStatus.value='';detailLoading.value=true;try{const row=rows.value.find(row=>row.key===query.row_key),parts=row?.compositions||{},cached=parts[query.kind]||parts[String(query.kind).replace(/^rate:/,'')];if(cached&&!includeRecords&&!query.source_key&&(query.cost_page||1)===1&&query.flow_page===1){detail.value=String(query.kind).startsWith('rate:')?{...cached,title:'费率 · '+cached.title,cost:undefined,records:[],records_total:0}:cached;return;}const data=await calculation(await fetchFinanceSummaryDetail(batch.value.dataset,{...query,...(includeRecords?{include_records:1}:{}),...(batch.value.direct_query?{query_context:queryContext.value}:{})},{signal}),()=>alive&&detailOpen.value&&version===detailRequest,detailStatus,true,signal);if(alive&&detailOpen.value&&version===detailRequest)detail.value=data;}catch(e){if(alive&&detailOpen.value&&version===detailRequest)detailError.value=e.message;}finally{if(alive&&detailOpen.value&&version===detailRequest)detailLoading.value=false;}}
const sourceDocument=html=>'<html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><style>body{font:13px sans-serif;color:#253753}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #dce4ef;text-align:left}small{display:block}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>'+html+'</body></html>';
const editorOpen=ref(false),fee=ref({}),feeError=ref('');const operationLabel=computed(()=>({save:fee.value.id?'修改':'新增',disable:'禁用',restore:'恢复',delete:'删除',exclude_source:'排除汇总',restore_source:'恢复汇总'}[fee.value.operation]||'修改'));
const feeClosed=computed(()=>{const code=options.value.stores.find(s=>String(s.id)===String(fee.value.store))?.code;return (options.value.closed_periods||[]).some(p=>p.month===fee.value.month&&(!p.shop||p.shop===code));});
const feeCurrency=computed(()=>fee.value.source_currency||options.value.stores.find(s=>String(s.id)===String(fee.value.store))?.currency||'请先选择店铺');
function editFee(row,operation='save'){if(showingPrevious.value)return;const month=applied.month||options.value.months[0]||'';feeError.value='';fee.value=row?{id:row.participation?row.source_id:row.edit_key||row.key,...(row.participation?{source_currency:row.original_currency||row.identity.currency}:{}),store:row.identity.store,month:row.record?.month||row.accounting_month||row.date.slice(0,7),date:row.accounting_date||row.date,kind:row.kind,mode:row.mode,order:row.identity.order||'',amount:money(row.record?.amount??row.original_amount??row.amount).replace(/,/g,''),reason:'',operation}:{store:applied.store||options.value.stores[0]?.id,month,date:month?month+'-01':'',kind:'order_fee',mode:'both',order:'',amount:'',reason:'',operation};editorOpen.value=true;}
watch(()=>fee.value.kind,kind=>{if(!fee.value.id){fee.value.mode=kind==='advertising'?'operations':'both';if(kind==='advertising')fee.value.order='';}});
async function submitFee(){if(saving.value||feeClosed.value||showingPrevious.value)return;saving.value=true;feeError.value='';try{const data=result(await saveFinanceSummaryFee(batch.value.dataset,{revision:batch.value.revision,record:['exclude_source','restore_source'].includes(fee.value.operation)?{id:fee.value.id,operation:fee.value.operation,reason:fee.value.reason}:{...fee.value}}));batch.value.revision=data.revision;editorOpen.value=false;await loadTable(page.value);}catch(e){feeError.value=e.message+'；请核对当前版本和操作记录后重试。';await refresh();}finally{saving.value=false;}}
const historyOpen=ref(false),history=ref({rows:[],total:0,page:1}),historyError=ref(''),historyLoading=ref(false),historyStatus=ref('');let historyRequest=0;
watch(historyOpen,open=>{if(!open){stopRead('history');historyRequest++;history.value={rows:[],total:0,page:1};historyLoading.value=false;historyError.value='';historyStatus.value='';cancelInactivePolls();}},{flush:'sync'});
async function showHistory(number){const signal=startRead('history');const version=++historyRequest;historyOpen.value=true;historyError.value='';historyStatus.value='';historyLoading.value=true;history.value={rows:[],total:0,page:number};try{const data=await calculation(await fetchFinanceSummaryHistory(batch.value.dataset,{page:number},{signal}),()=>alive&&historyOpen.value&&version===historyRequest,historyStatus,true,signal);if(alive&&historyOpen.value&&version===historyRequest)history.value=data;}catch(e){if(alive&&historyOpen.value&&version===historyRequest)historyError.value=e.message;}finally{if(alive&&historyOpen.value&&version===historyRequest)historyLoading.value=false;}}
onMounted(()=>{refresh();autoTimer=window.setInterval(checkForChanges,30000);document.addEventListener('visibilitychange',checkForChanges);});
onBeforeUnmount(()=>{alive=false;for(const key of readControllers.keys())stopRead(key);requestVersion++;detailRequest++;historyRequest++;cancelTableWait();window.clearInterval(autoTimer);for(const finish of pollWaiters)finish();pollWaiters.clear();document.removeEventListener('visibilitychange',checkForChanges);});
</script>

<style scoped>
.period-totals{display:flex;flex-wrap:wrap;gap:10px 20px;padding:12px 14px;border-top:1px solid #dce5f3;font-size:12px}.totals-scope{width:100%;color:#60718a}
.heading-copy{margin-right:auto}.heading-copy p{margin:6px 0 0;color:#60718a;font-size:12px}
.flow-more{align-self:center;color:#60718a}.flow-more summary{cursor:pointer}.flow-more[open]{flex-basis:100%}.flow-more[open] .filters{margin-top:12px}
.finance-native .primary-action{color:#fff;background:#255ff2;border-color:#255ff2}.finance-native .primary-action:disabled{opacity:.55}
.finance-native .scope-filters{padding:16px;background:#fff;border:1px solid #dce5f3;border-radius:8px;gap:12px;align-items:flex-end}
.scope-filters .filter-pending{flex-basis:100%;margin:0}
.scope-filters .period-context,.scope-filters .period-fields{display:contents}.scope-filters label{flex:1;min-width:105px}.scope-filters label select{width:100%;min-width:0}.scope-filters .period-fields label{flex:1.4;min-width:160px}.scope-filters label:has(input){max-width:240px}
.finance-native .view-bar{border:0;padding:0;gap:12px}.view-bar nav{gap:6px}.view-bar nav button{border:0;border-radius:4px;margin:0;background:transparent;color:#526176;padding:10px 12px}.view-bar nav button[aria-current]{background:#eaf1ff;color:#255ff2}.view-bar .pending-link{margin-left:auto;border:0;background:transparent;color:#255ff2}
.table-workbench{min-width:0;border:1px solid #dce5f3;border-radius:8px;background:#fff;overflow:hidden}.result-toolbar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:12px 14px;border-bottom:1px solid #dce5f3}.result-context,.result-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.result-context{color:#60718a;font-size:12px}.result-context .count{margin:0}.result-actions .view-options{gap:6px}.table-workbench .table-scroll{border:0;max-height:clamp(320px,calc(100vh - 390px),680px)}.table-workbench .pagination{padding:12px 14px;border-top:1px solid #dce5f3}.flow-filters{padding:14px;border-bottom:1px solid #dce5f3}.flow-filters input{max-width:160px}.table-workbench td{padding-top:14px;padding-bottom:14px}.ledger-table th{font-weight:400;color:#60718a}.table-workbench .empty{margin:0}.table-workbench .query-progress{margin:12px}
@media(max-width:600px){.scope-filters label,.scope-filters .period-fields label{flex-basis:calc(50% - 12px);min-width:0}.scope-filters label:has(input){max-width:none}.result-toolbar{align-items:flex-start}.result-actions{width:100%;justify-content:flex-end}.flow-filters label{flex:1;min-width:125px}.flow-filters input{width:100%;max-width:none}.heading-copy{flex-basis:100%}}
.source-disclosure,.reconciliation-disclosure,.calculation-disclosure{font-size:12px;color:#526176;min-width:0}
.source-disclosure summary,.reconciliation-disclosure>summary,.calculation-disclosure summary{cursor:pointer;width:fit-content;max-width:100%;line-height:1.6}
.source-disclosure[open],.reconciliation-disclosure[open],.calculation-disclosure[open]{padding-bottom:8px}
.source-disclosure p,.calculation-disclosure p{max-width:100ch;line-height:1.7;margin:8px 0}
.view-bar{padding-top:8px;border-top:1px solid #d7e1ef}
.view-bar>[aria-label="财务指标展示方式"]{margin-left:0;gap:8px}
.view-bar>[aria-label="财务指标展示方式"]>span{display:none}
.field-anomaly{border:0;background:transparent;color:#b45309;padding:2px 5px;cursor:help;font-size:14px;vertical-align:middle;}
.field-anomaly:focus-visible{outline:2px solid currentColor;outline-offset:2px;}
.query-progress{padding:12px 16px;background:#edf4ff;border:1px solid #c6d3e5;border-radius:4px;color:#29466e}
.view-options button[aria-pressed="true"]{background:#255ff2;color:#fff;border-color:#255ff2}
.metric-pair{display:flex;justify-content:space-between;gap:12px}.metric-pair small{margin:0}.metric-cell{text-align:right}

.summary-status{margin:16px 0;padding:16px 20px;border:1px solid #e9b8b8;background:#fff6f5;border-radius:8px;color:#782323}.summary-status p{margin:8px 0 14px;max-width:75ch;line-height:1.6}

.attribution-context{display:grid;gap:8px;padding:12px 0;border-bottom:1px solid #d7e1ef}.attribution-context summary{cursor:pointer;color:#29466e}.attribution-context button[aria-pressed="true"]{color:#fff;background:#255ff2;border-color:#255ff2}.attribution-scroll{overflow:auto;max-height:300px}.attribution-scroll th{position:static}.attribution-scroll .parts{margin:8px 0}
.period-types button:first-child,.period-types button:last-child{border-radius:4px}
.period-context{display:flex;align-items:flex-end;flex-wrap:wrap;gap:12px 20px;padding:0;border:0}.period-types{gap:8px;flex-wrap:wrap}.period-types button{margin:0;border-radius:4px;padding:10px 24px;font-weight:600}.period-types button[aria-pressed="true"]{color:#fff;background:#255ff2;border-color:#255ff2}.period-fields{display:flex;align-items:flex-end;flex-wrap:wrap;gap:12px 16px}.period-fields label{display:grid;gap:6px}.period-fields select{min-width:160px}.view-bar nav{flex-wrap:wrap;row-gap:8px}
.finance-native{display:grid;gap:12px;min-width:0;color:#253753;font-size:13px}.page-heading,.view-bar,.pagination,.view-options{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.page-heading h1{font-size:20px;color:#172033;margin:0 auto 0 0}.batch-caption{flex:1;font-size:12px;color:#526176}.batch-caption summary{cursor:pointer}.batch-caption p{margin:6px 0}.filters{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px 16px}.filters label,.fee-form label{display:grid;gap:6px}.filters select{min-width:120px}.filters input{width:185px}button,select,input,textarea{font:inherit;border:1px solid #c6d3e5;border-radius:4px;background:#fff;color:#29466e;padding:8px 12px}button{cursor:pointer;white-space:nowrap}button:disabled{cursor:default;opacity:.55}button:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #255ff2;outline-offset:2px}nav{display:flex}nav button{border-radius:0;margin-right:-1px}nav button:first-child{border-radius:4px 0 0 4px}nav button:last-child{border-radius:0 4px 4px 0}nav button[aria-current]{color:white;background:#255ff2;border-color:#255ff2}.count{margin-left:auto;color:#526176}.view-options{font-size:12px;color:#526176}.view-options select{margin-left:8px}.table-scroll{position:relative;overflow:auto;max-height:clamp(300px,calc(100vh - 365px),650px);border:1px solid #d7e1ef;background:#fff;min-height:120px}.table-scroll table{border-collapse:separate;border-spacing:0;min-width:100%}th,td{padding:12px;vertical-align:top;text-align:left;border-bottom:1px solid #dce5f3;white-space:nowrap}th{font-size:12px;background:#eff4fa;position:sticky;top:32px;z-index:2}.bands th{top:0;height:32px;box-sizing:border-box;padding:7px 12px;background:#e7eef8;border-right:1px solid #fff}.summary-table tbody td:first-child,.ledger-table tbody td:first-child{position:sticky;left:0;background:#fff;z-index:1}.summary-table thead tr:last-child th:first-child,.ledger-table th:first-child{left:0;z-index:3}.ledger-table th{top:0}tbody tr:nth-child(even) td{background:#f5f8fd}.summary-table tbody tr:nth-child(even) td:first-child,.ledger-table tbody tr:nth-child(even) td:first-child{background:#f5f8fd}.identity-cell{position:sticky;background:#fff;z-index:2;overflow:hidden;text-overflow:ellipsis}.summary-table th.identity-cell{z-index:4;background:#eff4fa}.bands th.identity-band{left:0;z-index:5}.summary-table tbody tr:nth-child(even) .identity-cell{background:#f5f8fd}.summary-table{table-layout:fixed}.product{min-width:250px;max-width:280px;white-space:normal;line-height:1.6}.product>span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.product a{font-size:11px;color:#365b89;display:block;margin-top:8px}small{display:block;color:#526176;font-size:11px;line-height:1.6;margin-top:3px}.amount{padding:0;border:0;background:transparent;color:inherit;text-align:right;white-space:nowrap;min-width:42px;font-variant-numeric:tabular-nums}.amount:hover{text-decoration:underline}.negative{color:#ce2323}.positive{color:#087b39}.unknown{color:#60718a}.profit{min-width:145px}.profit>div{display:flex;justify-content:space-between;gap:16px}.profit small{display:inline}.description{min-width:250px;max-width:420px;white-space:normal;line-height:1.6}.actions{display:flex;gap:6px;flex-wrap:wrap}.actions button{padding:6px 10px}.loading{position:sticky;left:0;top:0;height:0;z-index:5;text-align:center;color:#29466e;pointer-events:none}.loading::first-line{background:#edf4ff}.pagination{justify-content:flex-end}.pagination>span:first-child{margin-right:auto;color:#64748b}.empty{padding:25px}.parts{border-collapse:collapse;width:100%;margin:16px 0}.parts th{position:static}.parts td{white-space:normal}.detail-note{font-size:12px;color:#526176;line-height:1.7}.source-frame{width:100%;height:70vh;border:0}.fee-form{display:grid;grid-template-columns:1fr 1fr;gap:16px}.fee-form .full{grid-column:1 / -1}.fee-form textarea{min-height:72px}@media(max-width:900px){.page-heading .batch-caption{order:4;flex-basis:100%}.count{margin-left:0}.table-scroll{max-height:55vh}.fee-form{grid-template-columns:1fr}}
.coverage-stores{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;max-height:260px;overflow:auto;border:1px solid #dce4ef;border-radius:6px;padding:12px}.coverage-stores label{display:flex;flex-direction:row;align-items:center;gap:6px}.coverage-stores input{min-width:0;width:auto;margin:0}@media(max-width:600px){.coverage-stores{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
