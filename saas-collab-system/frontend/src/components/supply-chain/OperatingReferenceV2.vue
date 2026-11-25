<template>
  <section class="reference-list" aria-label="国家订货参考清单">
    <el-alert v-if="auth.authorizationStale" title="账号权限正在刷新，请刷新授权后重新读取补货参考。" type="warning" :closable="false" />
    <p>清单以国家＋普通商品SKU汇总。普通商品直接销量与组合商品折算组件销量参与计算；虚拟商品和组合商品本身不生成采购建议。</p>
    <div class="strategy-summary" v-if="strategy"><strong>{{ strategy.name || '国家补货策略' }}</strong><span>订货间隔 {{ strategy.cycle_days }} 天</span><span>预计到仓 {{ strategy.lead_days }} 天</span><span>安全库存 {{ strategy.safety_days }} 天</span><span>权重 7/15/30 天：{{ weightsLabel }}</span><small>策略版本 {{ strategy.version ?? strategy.id ?? '—' }} · 销量截止 {{ salesEnd || '昨天' }}</small></div>
    <el-alert v-if="strategyNotice" :title="strategyNotice" type="warning" :closable="false" />
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
    <div class="reference-actions">
      <el-select v-model="analysisMode" aria-label="参考分析方式"><el-option label="国家汇总" value="country"/><el-option label="按平台分析" value="platform"/></el-select>
      <el-select v-if="analysisMode==='platform'" v-model="platformType" placeholder="选择平台" aria-label="参考分析平台"><el-option v-for="option in platformOptions" :key="option.platform_type" :label="option.name" :value="option.platform_type"/></el-select>
    </div>
    <p class="muted">补货参考每日夜间更新。平台使用国家共享库存，订货按国家汇总。</p>
    <div class="reference-actions"><el-button type="primary" :loading="loading" :disabled="blocked || !strategy?.active" @click="generate">查询补货参考</el-button><el-tag v-if="jobStatus" :type="jobStatus==='completed'?'success':jobStatus==='failed'?'danger':['queued','running'].includes(jobStatus)?'warning':'info'">{{jobStatusLabel}}</el-tag></div>
    <el-progress v-if="jobId && ['queued','running'].includes(jobStatus)" :percentage="progressPercent" :status="jobStatus==='failed'?'exception':undefined" :format="progressText" />
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div v-if="jobStatus==='failed'" class="job-error"><span>{{jobError || '读取失败，请重试。'}}</span><el-button type="primary" :disabled="blocked || loading" @click="generate">重试</el-button></div>
    <template v-if="jobStatus==='completed'">
      <p class="muted">{{ jobId.startsWith('daily:') ? `每日结果生成时间 ${dateTime(generatedAt)}` : `计算观察期间 ${dateTime(observationStart)} 至 ${dateTime(observationEnd || generatedAt)}` }} · 销量截止 {{ salesEnd || '—' }} · 策略版本 {{ jobStrategyVersion || strategy?.version || '—' }}。{{ formula }} {{ revalidationNote }}</p>
      <div class="result-summary"><div><strong>{{ number(summary.positive_count) }}</strong><span>建议新增</span></div><div><strong>{{ number(summary.unknown_count) }}</strong><span>数据待核对</span></div><div><strong>{{ number(summary.awaiting_procurement_count) }}</strong><span>已有需求待采购</span></div><div><strong>{{ number(summary.arrival_risk_count) }}</strong><span>到货风险</span></div><div><strong>{{ number(totalRows) }}</strong><span>当前筛选结果</span></div></div>
      <div class="reference-actions result-filters"><el-input v-model="search" clearable placeholder="搜索新旧SKU／商品名称" aria-label="参考商品搜索" @keyup.enter="loadRows(0)" :disabled="loading"/><el-select v-model="filter" aria-label="建议筛选" @change="loadRows(0)" :disabled="loading"><el-option label="已有数据参考" value="observed"/><el-option label="建议新增量大于0" value="positive"/><el-option label="全部商品" value="all"/><el-option label="无需新增" value="zero"/><el-option label="异常商品待处理" value="unknown"/></el-select><el-select v-model="riskFilter" aria-label="风险筛选" placeholder="全部风险" @change="loadRows(0)" :disabled="loading"><el-option label="全部风险" value=""/><el-option label="已有需求待采购" value="awaiting_procurement"/><el-option label="需补货" value="replenish"/><el-option label="到货前有缺口" value="arrival_gap"/><el-option label="已缺货" value="out_of_stock"/><el-option label="新品／无销量" value="new_or_zero_sales"/><el-option label="数据待核对" value="data_check"/></el-select><el-select v-model="abcGradeFilter" aria-label="综合ABC筛选" placeholder="全部综合ABC" @change="loadRows(0)" :disabled="loading"><el-option label="全部综合ABC" value=""/><el-option label="A" value="A"/><el-option label="B" value="B"/><el-option label="C" value="C"/><el-option label="新品观察" value="new"/><el-option label="无有效销售贡献" value="no_sales"/><el-option label="未分类" value="unavailable"/></el-select><el-cascader v-model="selectedCategories" :options="categoryTree" :props="{ multiple: true, checkStrictly: true, emitPath: false }" clearable filterable collapse-tags placeholder="选择商品品类" aria-label="商品品类" /><el-button :loading="loading" @click="loadRows(0)">查询</el-button><el-popover trigger="click" width="260"><template #reference><el-button>列设置</el-button></template><el-checkbox-group v-model="visibleColumns"><el-checkbox v-for="column in optionalColumns" :key="column.key" :value="column.key">{{ column.label }}</el-checkbox></el-checkbox-group><el-button link @click="restoreColumns">恢复默认</el-button></el-popover></div>
      <div v-if="floatingBasket && analysisMode==='country'" class="reference-actions">
        <el-button :disabled="loading" @click="switchResultView">{{ groupedView ? '按 SKU 查看' : '按整款查看' }}</el-button>
      </div>
      <div v-if="groupedView" class="table-scroll" v-loading="loading">
        <el-table :data="rows" row-key="spu_id" :expand-row-keys="expandedSpus" border @expand-change="expandSpu" @sort-change="changeSort" empty-text="当前筛选下暂无商品">
          <el-table-column type="expand" width="48"><template #default="{row: group}">
            <section class="sku-details" :aria-label="`${group.spu_code} SKU明细`" v-loading="skuDetails[group.spu_id]?.loading">
              <p class="muted">{{group.spu_name}} · 全部 {{number(group.sku_count)}} 个 SKU，其中 {{number(group.matched_sku_count)}} 个符合当前筛选。</p>
              <el-alert v-if="skuDetails[group.spu_id]?.error" :title="skuDetails[group.spu_id].error" type="error" :closable="false" />
      <el-table :data="skuDetails[group.spu_id]?.rows || []" border empty-text="暂无 SKU 明细">
        <el-table-column v-if="visibleColumns.includes('abc')" label="综合 ABC" min-width="220"><template #default="{row}"><InventoryAbcBadges :row="row" entity-type="sku"/></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('image')" label="商品图片" width="100"><template #default="{row}"><OperatingProductImageV2 :sku-id="row.sku_id" :source="row.image_preview_url || row.product_details?.image_url || ''"/></template></el-table-column>
        <el-table-column label="SKU / 商品" min-width="200"><template #default="{row}"><DocumentSkuV2 :sku="row.sku_code || row.sku" :legacy-sku-code="row.legacy_sku_code"/><small>{{row.product_name}}</small><el-tag v-if="row.product_status" size="small" :type="productStatusType(row.product_status)">{{productStatusLabel(row.product_status)}}</el-tag></template></el-table-column>
        <el-table-column v-for="column in reportColumns.filter(item => visibleColumns.includes(item.key))" :key="column.key" :prop="column.key" :label="column.label" min-width="120"><template #default="{ row }">{{ reportValue(row, column.key) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('forecast')" label="预测日销量" width="115"><template #default="{row}">{{ number(row.forecast_daily_sales) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('shortage')" label="预计缺货日期" width="140"><template #default="{row}">{{ row.business_decision?.first_shortage_date || (row.business_decision && row.business_decision.category !== 'unavailable' ? '覆盖期内充足' : '—') }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('reference')" label="处理动作" min-width="150"><template #default="{row}"><strong>{{ row.business_decision?.category_label || '查看计算依据' }}</strong><small v-if="row.business_decision?.requires_expedite">预计 {{row.business_decision.first_shortage_date}} 缺货，需催货或调拨</small></template></el-table-column>

        <el-table-column v-if="visibleColumns.includes('supply')" label="在途与订货占用" min-width="185"><template #default="{row}"><div>发货在途 {{ number(row.business_decision?.incoming_quantity) }}</div><div>已提交需求 {{ number(row.submitted_demand) }}</div><div>草稿预留 {{ number(row.draft_reserved_demand) }}</div></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('coverage')" label="在库可售" width="105"><template #default="{row}">{{ days(row.on_hand_days ?? row.coverage_days) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('eta')" label="最近预计到仓" min-width="145"><template #default="{row}">{{ etaDate(row.next_eta) }}<small v-if="row.next_eta?.quantity">{{ number(row.next_eta.quantity) }} 件</small></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('gap')" label="采购落实缺口" width="120"><template #default="{row}">{{ number(row.replenishment_gap) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('suggested_quantity')" label="建议新增量" prop="suggested_quantity" width="115"><template #default="{row}"><strong>{{ number(row.suggested_quantity ?? (row.recognized_reference?.confirmed_deductions ? row.recognized_reference.quantity_reference : null)) }}</strong><small v-if="row.suggested_quantity == null && row.recognized_reference?.confirmed_deductions && row.recognized_reference.has_observed_basis">按已知数据</small></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('risk')" label="依据" width="130"><template #default="{row}"><el-button link type="primary" @click="openEvidence(row)">查看计算依据</el-button></template></el-table-column>
        <el-table-column v-if="audience==='operator' && analysisMode==='country'" label="选择" width="70" fixed="right"><template #default="{row}"><el-checkbox :model-value="!!chosen[row.sku_id]" :disabled="loading || !Number(row.suggested_quantity) || Number(row.suggested_quantity)<0" :aria-label="`选择${row.sku_code || row.sku}`" @change="value=>toggle(row,value)"/></template></el-table-column>
      </el-table>

              <div class="reference-actions"><el-button v-if="skuDetails[group.spu_id]?.error" @click="loadSkuDetails(group)">重试明细</el-button><el-pagination :current-page="skuDetails[group.spu_id]?.page || 1" :page-size="20" :total="skuDetails[group.spu_id]?.total || 0" layout="total, prev, pager, next" @current-change="value=>loadSkuDetails(group,value-1)" /></div>
            </section>
          </template></el-table-column>
          <el-table-column v-if="visibleColumns.includes('abc')" label="综合 ABC" min-width="220"><template #default="{row}"><InventoryAbcBadges :row="row" entity-type="spu"/></template></el-table-column>
          <el-table-column label="商品图片" width="100"><template #default="{row}"><OperatingProductImageV2 v-if="row.image_sku_id" :sku-id="row.image_sku_id" :source="row.image_preview_url || ''"/><span v-else class="muted">暂无在售图片</span></template></el-table-column>
          <el-table-column label="SPU / 商品" min-width="240"><template #default="{row}"><strong>{{row.spu_code || '未维护新SPU'}}</strong><small>旧 SPU：{{row.legacy_spu_code || '未维护'}}</small><div>{{row.spu_name}}</div></template></el-table-column>
          <el-table-column label="SKU数量" width="120"><template #default="{row}">{{number(row.sku_count)}}<small>匹配 {{number(row.matched_sku_count)}}</small></template></el-table-column>
          <el-table-column v-for="column in spuColumns" :key="column.key" :label="column.label" :prop="column.key" sortable="custom" min-width="130"><template #default="{row}">{{number(row[column.key])}}</template></el-table-column>
          <el-table-column label="处理情况" min-width="160"><template #default="{row}"><div>建议采购 {{number(row.purchase_count)}} 个 SKU</div><div>需催货 {{number(row.expedite_count)}} 个 SKU</div></template></el-table-column>
          <el-table-column label="明细" width="110" fixed="right"><template #default="{row}"><el-button link type="primary" @click="toggleSpu(row)">{{expandedSpus.includes(row.spu_id)?'收起':'展开 SKU'}}</el-button></template></el-table-column>
        </el-table>
      </div>
      <div v-else class="table-scroll" v-loading="loading"><el-table :data="rows" border @sort-change="changeSort" empty-text="当前筛选下暂无商品">
        <el-table-column v-if="visibleColumns.includes('abc')" label="综合 ABC" min-width="220"><template #default="{row}"><InventoryAbcBadges :row="row" entity-type="sku"/></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('image')" label="商品图片" width="100"><template #default="{row}"><OperatingProductImageV2 :sku-id="row.sku_id" :source="row.image_preview_url || row.product_details?.image_url || ''"/></template></el-table-column>
        <el-table-column label="SKU / 商品" min-width="200"><template #default="{row}"><DocumentSkuV2 :sku="row.sku_code || row.sku" :legacy-sku-code="row.legacy_sku_code"/><small>{{row.product_name}}</small><el-tag v-if="row.product_status" size="small" :type="productStatusType(row.product_status)">{{productStatusLabel(row.product_status)}}</el-tag></template></el-table-column>
        <el-table-column v-for="column in reportColumns.filter(item => visibleColumns.includes(item.key))" :key="column.key" :prop="column.key" :label="column.label" :sortable="column.sortable ? 'custom' : false" min-width="120"><template #default="{ row }">{{ reportValue(row, column.key) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('forecast')" label="预测日销量" width="115"><template #default="{row}">{{ number(row.forecast_daily_sales) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('reference')" label="已确认数据参考" min-width="220"><template #default="{row}"><template v-if="row.recognized_reference"><div>可用库存 {{ number(row.recognized_reference.observed_available_stock) }}</div><small v-for="(window, days) in row.recognized_reference.observed_sales_windows" :key="days">近{{days}}天销量 {{ number(window) }} · 日均 {{ number(window == null ? null : window / Number(days)) }}</small><div v-if="row.recognized_reference.has_observed_basis">初步缺口参考 {{ number(row.recognized_reference.quantity_reference) }}</div><small v-if="row.recognized_reference.has_observed_basis">参考缺口尚未扣除在途及订货占用。</small></template><span v-else-if="row.suggested_quantity == null">暂无完整参考依据</span><span v-else>—</span><small v-for="issue in row.recognized_reference?.scope_issues || []" :key="issue" class="issue">范围异常：{{issueLabel(issue)}}</small><small v-for="issue in row.recognized_reference?.item_issues || []" :key="issue" class="issue">商品异常：{{issueLabel(issue)}}</small></template></el-table-column>
        <el-table-column v-if="analysisMode==='platform' && visibleColumns.includes('platform')" label="平台销量与日均（参与本平台建议）" min-width="240"><template #default="{row}"><small v-for="window in platformRows(row)" :key="window.period">{{window.period}}：{{number(window.units)}} 件 · 日均 {{number(window.daily_units)}} 件</small><small>本平台销量用于计算本平台建议；库存为国家共享库存参考。各平台建议不可直接相加。</small></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('supply')" label="库存与供应" min-width="185"><template #default="{row}"><div>可用 {{ number(row.available_stock) }} · 有效到货 {{ number(row.valid_incoming ?? row.in_transit_stock) }}</div><div>已提交需求 {{ number(row.submitted_demand) }}</div><div>草稿预留 {{ number(row.draft_reserved_demand) }}</div></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('coverage')" label="在库可售" width="105"><template #default="{row}">{{ days(row.on_hand_days ?? row.coverage_days) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('eta')" label="最近预计到仓" min-width="145"><template #default="{row}">{{ etaDate(row.next_eta) }}<small v-if="row.next_eta?.quantity">{{ number(row.next_eta.quantity) }} 件</small></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('gap')" label="采购落实缺口" width="120"><template #default="{row}">{{ number(row.replenishment_gap) }}</template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('suggested_quantity')" label="建议新增量" prop="suggested_quantity" sortable="custom" width="115"><template #default="{row}"><strong>{{ number(row.suggested_quantity) }}</strong></template></el-table-column>
        <el-table-column v-if="visibleColumns.includes('risk')" label="风险 / 依据" min-width="205"><template #default="{row}"><el-tag size="small" :type="riskType(row.risk_level)">{{ riskLabel(row.risk_level) }}</el-tag><small v-for="issue in row.issues || []" :key="issue">{{issueLabel(issue)}}</small><el-button link type="primary" @click="openEvidence(row)">查看公式与来源</el-button></template></el-table-column>
        <el-table-column v-if="audience==='operator' && analysisMode==='country'" label="选择" width="70" fixed="right"><template #default="{row}"><el-checkbox :model-value="!!chosen[row.sku_id]" :disabled="loading || !Number(row.suggested_quantity) || Number(row.suggested_quantity)<0" :aria-label="`选择${row.sku_code || row.sku}`" @change="value=>toggle(row,value)"/></template></el-table-column>
      </el-table></div>
      <div class="reference-actions"><el-button v-if="audience==='operator' && analysisMode==='country'" :disabled="loading" @click="selectPage">勾选本页建议商品</el-button><el-button v-if="audience==='operator' && analysisMode==='country'" :disabled="!selectedRows.length" @click="chosen={}">清空勾选</el-button><span v-if="audience==='operator' && analysisMode==='country'">已选 {{selectedRows.length}} 个SKU（跨筛选和分页保留，最多100个）</span><el-button v-if="audience==='operator' && analysisMode==='country'" type="primary" :disabled="blocked || jobStatus!=='completed' || !jobId || !selectedRows.length" @click="floatingBasket ? openBasket() : emitSelection()">带入运营订货草稿</el-button><el-button v-else type="primary" @click="$emit('procurement')">前往采购协同</el-button><el-pagination v-model:current-page="page" :page-size="pageSize" :total="totalRows" layout="total, prev, pager, next" @current-change="loadCurrentPage" /></div>
    </template>
    <div v-if="audience==='operator' && analysisMode==='country' && floatingBasket" class="order-basket-fab" aria-label="运营订货草稿购物篮">
      <el-button type="primary" class="basket-trigger" aria-label="查看运营订货草稿购物篮" @click="openBasket">
        <span class="basket-icon" aria-hidden="true">🛒</span><span>运营订货草稿</span><el-tag effect="dark" type="info">{{selectedRows.length}} SKU · {{number(selectedQuantity)}}</el-tag>
      </el-button>
    </div>
    <el-drawer v-if="audience==='operator' && analysisMode==='country' && floatingBasket" v-model="basketOpen" title="运营订货草稿购物篮" direction="rtl" size="min(620px, 96vw)" :append-to-body="true" class="order-basket-drawer">
      <p class="muted">已选 {{selectedRows.length}} 个 SKU，建议新增量合计 {{number(selectedQuantity)}} 件。选中内容会带入可编辑草稿；确认前不会保存或提交。</p>
      <div v-if="selectedRows.length" class="basket-lines">
        <article v-for="row in selectedRows" :key="row.sku_id" class="basket-line">
          <div class="basket-line-main"><DocumentSkuV2 :sku="row.sku_code || row.sku" :legacy-sku-code="row.legacy_sku_code"/><strong>{{row.product_name || '未命名商品'}}</strong><small>新 SPU：{{row.spu_code || '未维护'}} · 旧 SPU：{{row.legacy_spu_code || '未维护'}}</small></div>
          <div class="basket-line-qty"><span>建议数量</span><strong>{{number(row.suggested_quantity)}} 件</strong></div>
          <el-button type="danger" link :aria-label="`移除${row.sku_code || row.sku}`" @click="removeBasketLine(row)">移除</el-button>
        </article>
      </div>
      <el-empty v-else description="购物篮为空。展开 SPU 后勾选有建议量的 SKU，即可加入这里复核。" />
      <template #footer>
        <div class="basket-footer"><el-button :disabled="!selectedRows.length" @click="clearBasket">清空购物篮</el-button><span class="basket-footer-spacer"/><el-button @click="basketOpen=false">继续选择</el-button><el-button type="primary" :disabled="basketConfirmDisabled" @click="confirmBasket">带入运营订货草稿</el-button></div>
      </template>
    </el-drawer>
    <el-dialog v-model="evidenceVisible" title="补货计算依据" width="min(720px,96vw)"><template v-if="evidenceRow"><h4>{{ evidenceRow.sku_code || evidenceRow.sku }} · {{ evidenceRow.product_name }}</h4><p>{{ evidence(evidenceRow).daily_sales_formula || formula }}</p><el-table :data="salesRows(evidenceRow)" border><el-table-column prop="period" label="参考期间"/><el-table-column prop="units" label="销量"/><el-table-column prop="daily_units" label="日均销量"/><el-table-column label="权重"><template #default="{row}">{{weightPercent(row.weight)}}</template></el-table-column></el-table><el-table v-if="evidenceRow.platform_analysis?.windows" :data="platformRows(evidenceRow)" border><el-table-column prop="period" label="平台分析期间"/><el-table-column prop="units" label="该平台销量"/><el-table-column prop="daily_units" label="该平台日均销量"/></el-table><small v-if="evidenceRow.platform_analysis" class="muted">平台 {{evidenceRow.platform_analysis.platform_type}} 销量参与本平台建议；库存为国家共享数据，各平台建议不可直接相加。</small><el-descriptions :column="2" border><el-descriptions-item label="目标覆盖天数">{{ evidence(evidenceRow).target_days ?? '—' }}</el-descriptions-item><el-descriptions-item label="目标备货量">{{ number(evidence(evidenceRow).target_stock) }}</el-descriptions-item><el-descriptions-item label="提醒线预测需求（到仓前＋安全库存）">{{ number(evidence(evidenceRow).reminder_stock) }}</el-descriptions-item><el-descriptions-item label="提醒线期间预计到货">{{ number(evidence(evidenceRow).reminder_incoming) }}</el-descriptions-item><el-descriptions-item label="是否触发订货提醒">{{ yesNo(evidence(evidenceRow).needs_replenishment) }}</el-descriptions-item><el-descriptions-item label="首次预计缺货日期">{{ shortageLabel(evidenceRow) }}</el-descriptions-item><el-descriptions-item label="到仓前是否有缺货">{{ yesNo(evidence(evidenceRow).arrival_gap) }}</el-descriptions-item><el-descriptions-item label="可用库存">{{ number(evidence(evidenceRow).available_stock ?? evidenceRow.available_stock) }}</el-descriptions-item><el-descriptions-item label="目标期有效到货">{{ number(evidence(evidenceRow).valid_incoming ?? evidenceRow.valid_incoming) }}</el-descriptions-item><el-descriptions-item label="采购落实缺口">{{ number(evidence(evidenceRow).replenishment_gap ?? evidence(evidenceRow).gap ?? evidenceRow.replenishment_gap) }}</el-descriptions-item><el-descriptions-item label="建议新增量">{{ number(evidence(evidenceRow).suggested_quantity ?? evidenceRow.suggested_quantity) }}</el-descriptions-item><el-descriptions-item label="已提交需求">{{ number(evidence(evidenceRow).submitted_demand ?? evidenceRow.submitted_demand) }}</el-descriptions-item><el-descriptions-item label="草稿预留需求">{{ number(evidence(evidenceRow).draft_reserved_demand ?? evidenceRow.draft_reserved_demand) }}</el-descriptions-item></el-descriptions><p><strong>公式代入：</strong>{{ substitutedFormula(evidenceRow) }}</p><p>趋势变化 {{ percent(evidenceRow.sales_trend_rate) }} · 在库可售 {{ days(evidenceRow.on_hand_days) }} · 含供应覆盖 {{ days(evidenceRow.supply_cover_days) }}</p><el-table :data="evidenceRow.warehouses || evidenceRow.warehouse_rows || []" border empty-text="没有仓库明细"><el-table-column prop="name" label="仓库"/><el-table-column prop="available_qty" label="可用库存"/><el-table-column prop="snapshot_at" label="快照时间"/></el-table><small v-for="issue in evidenceRow.issues || []" :key="issue" class="issue">{{issueLabel(issue)}}</small></template></el-dialog>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { fetchDailyReplenishment, fetchReplenishmentJobRows, fetchReplenishmentStrategy } from '../../api/replenishmentStrategyV2';
import { cockpitActorKey } from '../../utils/cockpitDraft';
import OperatingProductImageV2 from './OperatingProductImageV2.vue';
import DocumentSkuV2 from './DocumentSkuV2.vue';
import InventoryAbcBadges from '../inventory/InventoryAbcBadges.js';

const props = defineProps({ parameters: { type: Object, required: true }, disabled: Boolean, floatingBasket: Boolean, handoffSearch: { type: String, default: '' }, audience: { type: String, default: 'operator' }, issueLabel: { type: Function, default: value => value } });
const emit = defineEmits(['select','procurement','strategy','source-change']);
const auth = useAuthStore();
const categories = ref([]);
const selectedCategories = ref([]);
const reportSort = ref({});
const categoryTree = computed(() => {
  const nodes = new Map(categories.value.map(item => [item.id, { value: item.id, label: item.name, children: [] }]));
  const roots = [];
  for (const item of categories.value) {
    const node = nodes.get(item.id);
    const parent = nodes.get(item.parent_id);
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
});
const reportColumns = [
  { key: 'spu_code', label: '新 SPU', sortable: true },
  { key: 'legacy_spu_code', label: '旧 SPU', sortable: true },
  { key: 'sku_code', label: '新 SKU', sortable: true },
  { key: 'legacy_sku_code', label: '旧 SKU', sortable: true },
  ...[7, 15, 30].map(days => ({ key: `sales_${days}`, label: `近${days}天销量`, sortable: true })),
  { key: 'available_stock', label: '可售库存', sortable: true },
  { key: 'purchase_unshipped', label: '已下采购单·待发货' },
];
const optionalColumns = [...reportColumns, ...[{ key: 'abc', label: '综合 ABC' },{ key: 'image', label: '商品图片' },{ key: 'forecast', label: '预测日销量' },{ key: 'reference', label: '已确认数据参考' },{ key: 'supply', label: '库存与供应' },{ key: 'coverage', label: '在库可售' },{ key: 'eta', label: '最近预计到仓' },{ key: 'gap', label: '采购落实缺口' },{ key: 'suggested_quantity', label: '建议新增量' },{ key: 'risk', label: '风险 / 依据' },{ key: 'platform', label: '平台销量与日均' }]];
const defaultColumns = optionalColumns.map(column => column.key).filter(key => !['legacy_spu_code', 'legacy_sku_code', 'sku_code'].includes(key));
const columnKey = computed(() => `replenishment-columns:${cockpitActorKey(auth.currentUser)}`);
const visibleColumns = ref([]);
watch(columnKey, key => {
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    const migrated = localStorage.getItem(`${key}:abc-v1`) === '1';
    visibleColumns.value = Array.isArray(saved) ? [...new Set([...(migrated ? [] : ['abc']), ...saved.filter(value => optionalColumns.some(column => column.key === value))])] : [...defaultColumns];
    localStorage.setItem(`${key}:abc-v1`, '1');
  } catch { restoreColumns(); }
}, { immediate: true });
watch(visibleColumns, columns => {
  try { localStorage.setItem(columnKey.value, JSON.stringify(columns)); } catch { /* Storage may be disabled. */ }
});
function restoreColumns() { visibleColumns.value = [...defaultColumns]; }
function changeSort({ prop, order }) {
  reportSort.value = order ? { sort: prop, direction: order === 'ascending' ? 'asc' : 'desc' } : {};
  loadRows(0);
}
function reportValue(row, key) {
  if (key === 'purchase_unshipped') return number(row.pipeline?.production_unshipped);
  if (key.startsWith('sales_')) {
    const days = key.slice(6);
    return number(evidence(row).sales?.[days]?.units ?? row.recognized_reference?.observed_sales_windows?.[days]);
  }
  return key === 'available_stock' ? number(row.available_stock) : (row[key] || '—');
}

const blocked = computed(() => props.disabled || auth.authorizationStale);
const sourceKind=ref(props.parameters.source_kind || 'cycle'), activityStart=ref(''), activityEnd=ref(''), activityFactor=ref(1), analysisMode=ref('country'), platformType=ref(''), platformOptions=ref([]), strategy=ref(null), strategyNotice=ref(''), salesEnd=ref('');
const search=ref(props.handoffSearch), filter=ref(props.handoffSearch ? 'all' : 'observed'), riskFilter=ref(''), abcGradeFilter=ref(''), rows=ref([]), chosen=ref({}), page=ref(1), pageSize=ref(20), totalRows=ref(0), summary=ref({}), loading=ref(false), error=ref(''), loadError=ref(''), generatedAt=ref(''), formula=ref('');
const jobId=ref(''),jobStatus=ref(''),jobProcessed=ref(0),jobTotal=ref(0),jobError=ref(''),jobStrategyVersion=ref(''),observationStart=ref(''),observationEnd=ref(''),revalidationNote=ref('');
const evidenceVisible=ref(false), evidenceRow=ref(null); let requestSequence=0,strategySequence=0,pollController=null,jobGeneration=0;
const selectedRows=computed(()=>Object.values(chosen.value));
const progressPercent=computed(()=>jobTotal.value?Math.min(100,Math.floor(jobProcessed.value*100/jobTotal.value)):0);
const jobStatusLabel=computed(()=>({queued:'排队中',running:'计算中',completed:'计算完成',failed:'计算失败',cancelled:'已取消',expired:'结果已过期'}[jobStatus.value]||''));
const weightPercent=value=>value==null?'—':`${Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2})}%`;
const weightsLabel=computed(()=>[7,15,30].map(day=>weightPercent(strategy.value?.sales_weights?.[day] ?? strategy.value?.sales_weights?.[String(day)])).join(' / '));
const dailyEligible=computed(()=>sourceKind.value==='cycle'&&!activityStart.value&&!activityEnd.value&&Number(activityFactor.value)===1);
const number=value=>value==null?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});
const dateTime=value=>{if(!value)return '—';const date=new Date(value);return Number.isNaN(date.getTime())?'—':date.toLocaleString('zh-CN',{hour12:false});};
const days=value=>value==null?'—':`${number(value)} 天`;
const etaDate=value=>value&&typeof value==='object'?(value.expected_date||value.date||'—'):(value||'—');
const percent=value=>value==null?'—':`${(Number(value)*100).toFixed(1)}%`;
const yesNo=value=>value==null?'待核对':(value===true||value==='true'?'是':'否');
const riskLabel=value=>({data_check:'数据待核对',new_or_zero_sales:'新品／无销量待评估',out_of_stock:'已缺货',arrival_gap:'到货前有缺口',replenish:'需补货',manual_review:'停售／暂停状态，人工复核',normal:'正常'}[value]||'待核对');
const riskType=value=>({data_check:'danger',new_or_zero_sales:'info',out_of_stock:'danger',arrival_gap:'warning',replenish:'warning',manual_review:'warning',normal:'success'}[value]||'info');
const lifecycleStatusMap={new:'新品',new_product:'新品',active:'正常',draft:'草稿',discontinued:'已停产',slow_moving:'滞销',clearance_candidate:'清仓候选',clearance:'清仓',archived:'已归档',unknown:'待维护'};
const salesStatusMap={on_sale:'销售中',selling:'销售中',not_listed:'未上架',paused:'暂停销售',stopped:'已停止销售',unknown:'待维护'};
const productStatusLabel=value=>{const [lifecycle,sales]=String(value||'').split('/');return [lifecycle&&`生命周期：${lifecycleStatusMap[lifecycle]||lifecycle}`,sales&&`销售状态：${salesStatusMap[sales]||sales}`].filter(Boolean).join('／')||'待维护';};
const productStatusType=value=>/discontinued|stopped|paused/.test(String(value))?'danger':/slow_moving|clearance/.test(String(value))?'warning':/active|on_sale|selling/.test(String(value))?'success':'info';
function evidence(row){return row.calculation_evidence||row.formula_evidence||{};}
function shortageLabel(row){const e=evidence(row);if(row.risk_level==='data_check')return '数据待核对';if(e.first_shortage_date)return e.first_shortage_date;if(row.risk_level==='new_or_zero_sales')return '近期无销量，暂不推算缺货日';return e.needs_replenishment==null?'数据待核对':'覆盖期内未预测到缺货';}
function substitutedFormula(row){const e=evidence(row),keys=['target_stock','available_stock','valid_incoming','submitted_demand','draft_reserved_demand'];if(keys.some(key=>e[key]==null)||e.suggested_quantity==null)return `${e.formula||'ceil(max(0,T-I-P-O-Q))'}（数据待核对）`;return `向上取整［最大值（0，${keys.map(key=>number(e[key])).join('－')}）］＝${number(e.suggested_quantity)}`;}
function salesRows(row){const sales=evidence(row).sales||{};return [7,15,30].map(day=>({period:`近${day}天`,...(sales[day]||sales[String(day)]||{})}));}
function platformRows(row){const windows=row.platform_analysis?.windows||{};return [7,15,30].map(day=>({period:`近${day}天`,...(windows[day]||windows[String(day)]||{})}));}
function issueLabel(code){return props.issueLabel(code);}
const wholeProductView=ref(true), basketOpen=ref(false);
const groupedView=computed(()=>props.floatingBasket && analysisMode.value==='country' && wholeProductView.value);
let detailEpoch=0;
const skuDetails=ref({}),expandedSpus=ref([]);
const spuColumns=[{key:'sales_30',label:'近30天销量合计'},{key:'available_stock',label:'可售库存合计'},{key:'production_unshipped',label:'采购待发合计'},{key:'incoming_quantity',label:'发货在途合计'},{key:'suggested_quantity',label:'建议新增量合计'}];
const selectedQuantity=computed(()=>selectedRows.value.reduce((sum,row)=>sum+Math.max(0,Number(row.suggested_quantity)||0),0));
const basketConfirmDisabled=computed(()=>blocked.value||loading.value||jobStatus.value!=='completed'||!jobId.value||!selectedRows.value.length);
function stopPolling(){pollController?.abort();pollController=null;}
function reset({clearJob=true}={}){clearDetails();basketOpen.value=false;requestSequence++;jobGeneration++;stopPolling();loading.value=false;rows.value=[];chosen.value={};page.value=1;totalRows.value=0;summary.value={};error.value='';jobError.value='';evidenceVisible.value=false;evidenceRow.value=null;if(clearJob){jobId.value='';jobStatus.value='';jobProcessed.value=0;jobTotal.value=0;generatedAt.value='';formula.value='';jobStrategyVersion.value='';observationStart.value='';observationEnd.value='';revalidationNote.value='';}}
async function loadStrategy(){const token=++strategySequence;strategy.value=null;loadError.value='';reset();if(blocked.value||!props.parameters.country_id)return;try{const response=await fetchReplenishmentStrategy(props.parameters.country_id);if(token!==strategySequence)return;if(!response?.success)throw new Error(response?.message||'国家补货策略读取失败。');const data=response.data||{},candidate=data.strategy||data;const isConfigured=data.configured!==false&&!!candidate?.id;strategy.value=isConfigured?candidate:null;if(!isConfigured)strategyNotice.value='该国家尚未配置补货策略，请先到供应链设置维护。';else strategyNotice.value=strategy.value.active===false?'当前国家策略已停用。':'';salesEnd.value=data.sales_end||'';emit('strategy',{...(strategy.value||{}),sales_end:salesEnd.value,configured:isConfigured});if(isConfigured&&strategy.value.active!==false&&dailyEligible.value)await generate(true);}catch(e){if(token===strategySequence)loadError.value=e.message||'国家补货策略读取失败。';}}
watch(()=>String(props.parameters.country_id||''),loadStrategy,{immediate:true});
watch(()=>JSON.stringify([props.parameters.source_kind,props.parameters.analysis_mode,props.parameters.platform_type,props.parameters.activity_start,props.parameters.activity_end,props.parameters.activity_factor,props.parameters.strategy_id,props.parameters.sales_end,props.parameters.exclude_operating_order_id]),()=>{if(jobId.value)reset();},{flush:'sync'});
watch(()=>JSON.stringify([cockpitActorKey(auth.currentUser),auth.authorizationStale]),()=>{strategySequence++;requestSequence++;loading.value=false;strategy.value=null;strategyNotice.value='';loadError.value='';error.value='';platformOptions.value=[];platformType.value='';salesEnd.value='';reset();if(!auth.authorizationStale)loadStrategy();},{flush:'sync'});
watch(()=>props.parameters.source_kind,value=>{if(['cycle','season'].includes(value))sourceKind.value=value;});
watch(sourceKind,value=>{if(props.parameters.source_kind!==value)emit('source-change',value);reset();});
watch(()=>JSON.stringify([activityStart.value,activityEnd.value,activityFactor.value,analysisMode.value,platformType.value]),reset);
onBeforeUnmount(()=>{requestSequence++;strategySequence++;jobGeneration++;stopPolling();});
function requestBody(){return {country_id:Number(props.parameters.country_id),...(strategy.value?.id?{strategy_id:strategy.value.id}:{}),...(salesEnd.value?{sales_end:salesEnd.value}:{}),...(props.parameters.exclude_operating_order_id?{exclude_operating_order_id:props.parameters.exclude_operating_order_id}:{}),source_kind:sourceKind.value,analysis_mode:analysisMode.value,...(analysisMode.value==='platform'?{platform_type:platformType.value}:{}),...(sourceKind.value==='season'?{activity_start:activityStart.value||null,activity_end:activityEnd.value||null,activity_factor:Number(activityFactor.value)}:{})};}
async function generate(automatic = false){if(blocked.value||!props.parameters.country_id||!strategy.value?.id||strategy.value.active===false)return;if(!dailyEligible.value){error.value='季节／活动补货暂无夜间结果，请查询常规补货参考。';return;}if(analysisMode.value==='platform'&&!platformType.value){error.value='请选择平台后查询。';return;}reset();const generation=jobGeneration,token=++requestSequence;loading.value=true;error.value='';try{const response=await fetchDailyReplenishment(requestBody());if(token!==requestSequence||generation!==jobGeneration)return;if(!response?.success){if(automatic===true&&response?.status===404)return;throw new Error(response?.message||'读取夜间补货结果失败。');}const data=response.data||{};jobId.value=String(data.id||'');if(!jobId.value)throw new Error('读取结果时未返回任务编号。');jobStatus.value=data.status||'completed';updateJob(data);if(jobStatus.value==='completed')await loadRows(0,generation);}catch(e){if(token===requestSequence){error.value=e.message||'读取夜间补货结果失败。';jobStatus.value='failed';jobError.value=error.value;}}finally{if(token===requestSequence)loading.value=false;}}
function updateJob(data={}){jobStatus.value=data.status||jobStatus.value;jobProcessed.value=Number(data.processed??jobProcessed.value);jobTotal.value=Number(data.total??jobTotal.value);jobError.value=data.error||data.error_message||'';generatedAt.value=data.generated_at||data.updated_at||data.created_at||generatedAt.value;jobStrategyVersion.value=data.strategy_version??jobStrategyVersion.value;observationStart.value=data.created_at||observationStart.value;observationEnd.value=data.updated_at||observationEnd.value;salesEnd.value=data.parameters?.sales_end||data.sales_end||salesEnd.value;formula.value=data.formula||formula.value;revalidationNote.value=data.revalidation_note||'';if(data.platform_options)platformOptions.value=data.platform_options;if(data.counts)summary.value={...summary.value,positive_count:data.counts.positive??summary.value.positive_count,unknown_count:data.counts.unknown??summary.value.unknown_count,zero_count:data.counts.zero??summary.value.zero_count,awaiting_procurement_count:data.counts.awaiting_procurement??summary.value.awaiting_procurement_count,arrival_risk_count:data.counts.arrival_gap??summary.value.arrival_risk_count};}
function progressText(){return `${number(jobProcessed.value)} / ${number(jobTotal.value)} 条`;}
function handleTerminal(status,message){clearDetails();basketOpen.value=false;jobStatus.value=status;jobError.value=message;rows.value=[];chosen.value={};evidenceVisible.value=false;evidenceRow.value=null;totalRows.value=0;summary.value={};stopPolling();}
async function loadRows(pageIndex=page.value-1,generation=jobGeneration){if(!jobId.value||jobStatus.value!=='completed'||blocked.value||generation!==jobGeneration)return;const token=++requestSequence;loading.value=true;error.value='';try{const params={...(groupedView.value?{group_by:"spu"}:{}),...reportSort.value,category_ids:selectedCategories.value.join(',')||undefined,quantity_filter:filter.value,risk_filter:riskFilter.value||undefined,...(abcGradeFilter.value?{abc_grade:abcGradeFilter.value}:{}),search:search.value.trim()||undefined,limit:pageSize.value,offset:Math.max(0,pageIndex)*pageSize.value};const response=await fetchReplenishmentJobRows(jobId.value,params,{signal:(pollController=new AbortController()).signal});if(token!==requestSequence||generation!==jobGeneration)return;if(!response?.success){if([403,404,410].includes(response?.http_status)||response?.code==='JOB_EXPIRED'){handleTerminal(response?.http_status===403?'failed':'expired',response.message||'结果已失效或当前账号无权访问，请重新查询。');return;}throw new Error(response?.message||'读取补货结果失败');}const data=response.data||{};if(data.status&&data.status!=='completed'){handleTerminal(data.status,data.status==='expired'?'结果已过期，请重新查询。':'任务状态已变化，请重新查询。');return;}categories.value=data.categories||[];rows.value=data.rows||[];totalRows.value=Number(data.count??0);if(data.counts)summary.value={...summary.value,positive_count:data.counts.positive??summary.value.positive_count,unknown_count:data.counts.unknown??summary.value.unknown_count,zero_count:data.counts.zero??summary.value.zero_count,awaiting_procurement_count:data.counts.awaiting_procurement??summary.value.awaiting_procurement_count,arrival_risk_count:data.counts.arrival_gap??summary.value.arrival_risk_count};page.value=Math.floor(params.offset/pageSize.value)+1;}catch(e){if(token===requestSequence)error.value=e.message||'读取补货结果失败';}finally{if(token===requestSequence){loading.value=false;pollController=null;}}}
watch(() => props.handoffSearch, value => {
  if (!value) return;
  search.value = value;
  filter.value = 'all';
  clearDetails();
  stopPolling();
  loadRows(0);
});
function loadCurrentPage(value){return loadRows(value-1);}
function toggle(row,value){if(analysisMode.value!=='country')return;const copy={...chosen.value};if(value){if(Number(row.suggested_quantity)>0&&!copy[row.sku_id]){if(Object.keys(copy).length>=100){error.value='最多选择100个SKU，请分单处理。';return;}copy[row.sku_id]=row;}}else delete copy[row.sku_id];chosen.value=copy;}
function clearDetails(){
  detailEpoch++;
  skuDetails.value={};
  expandedSpus.value=[];
}
function switchResultView(){
  clearDetails();
  wholeProductView.value=!wholeProductView.value;
  reportSort.value={};
  loadRows(0);
}
async function loadSkuDetails(group,pageIndex=0,generation=jobGeneration){
  if(blocked.value || generation!==jobGeneration || !jobId.value)return;
  const id=group.spu_id,currentJob=jobId.value,epoch=detailEpoch;
  const token=(skuDetails.value[id]?.token || 0)+1;
  skuDetails.value={...skuDetails.value,[id]:{...skuDetails.value[id],loading:true,error:'',token}};
  try{
    const response=await fetchReplenishmentJobRows(currentJob,{group_by:'sku',spu_id:id,quantity_filter:'all',limit:20,offset:pageIndex*20});
    if(generation!==jobGeneration || epoch!==detailEpoch || currentJob!==jobId.value || skuDetails.value[id]?.token!==token)return;
    if(!response?.success)throw Error(response?.message || 'SKU明细读取失败');
    const data=response.data || {};
    skuDetails.value={...skuDetails.value,[id]:{rows:data.rows || [],total:Number(data.count || 0),page:pageIndex+1,loading:false,error:'',token}};
  }catch(e){if(generation===jobGeneration && epoch===detailEpoch && currentJob===jobId.value && skuDetails.value[id]?.token===token)skuDetails.value={...skuDetails.value,[id]:{...skuDetails.value[id],loading:false,error:e.message || 'SKU明细读取失败'}};}
}
function expandSpu(group,expanded){
  expandedSpus.value=expanded.map(row=>row.spu_id);
  if(expandedSpus.value.includes(group.spu_id) && !skuDetails.value[group.spu_id])void loadSkuDetails(group);
}
function toggleSpu(group){
  const id=group.spu_id;
  if(expandedSpus.value.includes(id))expandedSpus.value=expandedSpus.value.filter(value=>value!==id);
  else{expandedSpus.value=[...expandedSpus.value,id];if(!skuDetails.value[id])void loadSkuDetails(group);}
}
async function selectPage(){
  if(!groupedView.value){rows.value.filter(row=>Number(row.suggested_quantity)>0).forEach(row=>toggle(row,true));return;}
  if(blocked.value || loading.value)return;
  const generation=jobGeneration,currentJob=jobId.value;
  loading.value=true;error.value='';
  try{
    for(const group of rows.value){
      let offset=0,more=true;
      while(more){
        const response=await fetchReplenishmentJobRows(currentJob,{group_by:'sku',spu_id:group.spu_id,quantity_filter:'positive',limit:20,offset});
        if(generation!==jobGeneration || currentJob!==jobId.value)return;
        if(!response?.success)throw Error(response?.message || '建议 SKU 读取失败');
        const data=response.data || {};
        for(const row of data.rows || []){toggle(row,true);if(selectedRows.value.length>=100){error.value='已选择100个SKU，请分单处理。';return;}}
        offset+=(data.rows || []).length;more=!!data.has_more && (data.rows || []).length>0;
      }
    }
  }catch(e){if(generation===jobGeneration)error.value=e.message || '建议 SKU 读取失败';}
  finally{if(generation===jobGeneration)loading.value=false;}
}

function emitSelection(){if(analysisMode.value!=='country'||blocked.value||jobStatus.value!=='completed'||!jobId.value||!selectedRows.value.length)return;emit('select',{parameters:{...requestBody(),job_id:jobId.value,activity_start:activityStart.value||null,activity_end:activityEnd.value||null,activity_factor:Number(activityFactor.value)},rows:selectedRows.value});}
function openEvidence(row){evidenceRow.value=row;evidenceVisible.value=true;}
function openBasket(){basketOpen.value=true;}
function removeBasketLine(row){toggle(row,false);}
function clearBasket(){chosen.value={};}
function confirmBasket(){if(basketConfirmDisabled.value)return;emitSelection();basketOpen.value=false;}
defineExpose({switchResultView,loadSkuDetails,toggleSpu,skuDetails,basketOpen,openBasket,confirmBasket,generate,loadRows,reset,toggle,selectPage,emitSelection,rows,strategy,selectedRows,requestBody,search,filter,riskFilter,abcGradeFilter,analysisMode,platformType,sourceKind,jobId,jobStatus,jobProcessed,jobTotal,progressPercent,summary,totalRows,page,openEvidence,evidenceRow,evidenceVisible,etaDate,weightPercent,productStatusLabel,evidence,salesRows,platformRows,yesNo});
</script>
<style scoped>
.reference-list{margin-top:16px}.reference-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.reference-actions>.el-input{width:min(280px,100%)}.reference-actions>.el-select{width:180px}.reference-actions>.el-date-editor{width:160px}.table-scroll{overflow:auto}.strategy-summary{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:12px;background:#f5f8fc;border-radius:8px;font-size:13px}.strategy-summary small{width:100%}.muted,small{color:#64748b;font-size:12px;line-height:1.7}.reference-list :deep(td small){display:block}.issue{display:block;color:#b42318}.strategy-summary strong{color:#1e3a8a}.result-summary{display:grid;grid-template-columns:repeat(5,minmax(100px,1fr));gap:10px;margin:12px 0}.result-summary>div{display:flex;flex-direction:column;padding:12px;background:#f5f8fc;border-radius:8px}.result-summary strong{font-size:20px;color:#1e3a8a}.result-summary span{font-size:12px;color:#64748b}.result-filters{margin-top:16px}.job-error{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px;border-radius:8px;background:#fff1f0;color:#b42318}@media(max-width:760px){.result-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.result-filters>.el-select{width:calc(50% - 5px)}}
.order-basket-fab{position:fixed;right:96px;bottom:20px;z-index:1800}.basket-trigger{height:48px;border-radius:24px;box-shadow:0 6px 20px #17255433;display:flex;align-items:center;gap:9px}.basket-icon{font-size:18px}.basket-lines{display:grid;gap:10px}.basket-line{display:flex;align-items:center;gap:14px;padding:12px;border:1px solid #e2e8f0;border-radius:8px}.basket-line-main{display:grid;gap:4px;flex:1;min-width:0}.basket-line-main :deep(.document-sku){font-size:14px}.basket-line-main strong{overflow-wrap:anywhere}.basket-line-main small{display:block}.basket-line-qty{display:grid;gap:4px;text-align:right;white-space:nowrap}.basket-line-qty span{font-size:12px;color:#64748b}.basket-footer{display:flex;align-items:center;gap:10px}.basket-footer-spacer{flex:1}.order-basket-drawer :deep(.el-drawer__body){overflow:auto}.order-basket-drawer :deep(.el-drawer__footer){padding-top:12px}
</style>
