<template>
  <AppPage :title="pageTitle" :subtitle="isArchivePage ? '统一维护供应链基础资料，采购单引用同一份档案。' : '支持运营需求拆单、手工和文件导入的采购单。'" :capability="errorMessage ? 'degraded' : 'connected'">
    <template #action v-if="!isArchivePage">
      <router-link to="/supply-chain/supplier-shipments"><el-button>供应商发货单</el-button></router-link>
      <router-link to="/supply-chain/notifications"><el-button>订单通知</el-button></router-link>
      <el-button @click="downloadTemplate" :loading="busy">下载导入模板</el-button>
      <el-button v-if="canManage" :disabled="busy" @click="openImport">Excel 导入</el-button>
      <el-button v-if="canManage" type="primary" :disabled="busy" @click="openCreate">新建采购单</el-button>
    </template>
    <el-alert v-if="!canView" title="当前账号没有采购协同查看权限。" type="warning" :closable="false" />
    <template v-else>
      <p v-if="!canManage" class="muted">当前为只读模式，可查看档案、采购明细与下载文件。</p>
      <el-tabs v-if="!isArchivePage" v-model="activeTab" @tab-change="changeTab">
        <el-tab-pane label="采购单" name="orders" />
        <el-tab-pane label="运营订货" name="operating" />
      </el-tabs>
      <OperatingSplitV2 v-if="activeTab === 'operating'" :can-view="canView" :can-manage="canManage" @open-order="openDetail" />
      <template v-else>
      <section class="filter-bar" aria-label="采购与档案筛选">
        <el-input v-model="filters.search" clearable :placeholder="activeTab === 'orders' ? '系统单号 / 备注单号 / 供应商' : '名称 / 编码 / SKU'" aria-label="关键词" @keyup.enter="applyFilters" />
        <template v-if="activeTab === 'orders'">
          <el-select v-model="filters.status" clearable placeholder="全部状态" aria-label="采购状态">
            <el-option v-for="(label, value) in statusLabels" :key="value" :label="label" :value="value" />
          </el-select>
          <el-select v-model="filters.source_kind" clearable placeholder="全部来源" aria-label="采购来源">
            <el-option label="手工" value="manual" /><el-option label="Excel 导入" value="import" />
          </el-select>
        </template>
        <el-select v-if="activeTab === 'prices'" v-model="filters.supplier_id" clearable filterable remote :remote-method="searchSuppliers" :loading="options.suppliers.loading" placeholder="全部供应商" aria-label="价格供应商" @visible-change="ensureSuppliers">
          <el-option v-for="item in options.suppliers.rows" :key="item.id" :label="optionLabel(item)" :value="item.id" />
          <template #footer><el-button v-if="hasMoreOptions('suppliers')" link @click="loadMoreOptions('suppliers')">加载更多供应商</el-button></template>
        </el-select>
        <el-button type="primary" plain @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button v-if="canManage && activeTab !== 'orders'" type="primary" @click="openArchive()">{{ activeTab === 'prices' ? '新增报价' : activeTab === 'freight' ? '新增货运公司' : '新增供应商' }}</el-button>
      </section>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon class="error-notice" />
      <div class="table-scroll" v-loading="loading">
        <el-table v-if="activeTab === 'orders'" :data="rows" border stripe empty-text="暂无采购单">
          <el-table-column label="系统采购单号" min-width="180" fixed="left"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">{{ row.number }}</el-button></template></el-table-column>
          <el-table-column prop="reference_number" label="备注单号" min-width="160" />
          <el-table-column prop="supplier_name" label="供应商" min-width="180" />
          <el-table-column prop="country_name" label="国家" min-width="120" />
          <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabels[row.status] || row.status }}</el-tag></template></el-table-column>
          <el-table-column label="来源" width="100"><template #default="{ row }">{{ sourceLabel(row.source_kind) }}</template></el-table-column>
          <el-table-column prop="order_date" label="采购日期" width="120" />
          <el-table-column prop="total_quantity" label="数量" width="100" align="right" />
          <el-table-column label="金额" width="140" align="right"><template #default="{ row }">{{ money(row.total_amount) }}<small v-if="!row.prices_complete" class="price-missing">待补单价</small></template></el-table-column>
          <el-table-column label="操作" width="210" fixed="right"><template #default="{ row }"><el-button size="small" @click="openDetail(row)">查看</el-button><router-link v-if="row.status === 'confirmed'" :to="`/supply-chain/supplier-shipments?order_id=${row.id}`"><el-button size="small">发货单</el-button></router-link></template></el-table-column>
        </el-table>
        <el-table v-else-if="activeTab === 'prices'" :data="rows" border stripe empty-text="暂无供应商报价">
          <el-table-column prop="supplier_name" label="供应商" min-width="180" /><el-table-column prop="sku" label="SKU" min-width="160" /><el-table-column prop="name" label="商品名称" min-width="180" />
          <el-table-column label="单价" width="130" align="right"><template #default="{ row }">{{ money(row.unit_price) }}</template></el-table-column>
          <el-table-column prop="effective_date" label="生效日期" width="120" /><el-table-column label="来源" width="120"><template #default="{ row }">{{ sourceLabel(row.source_kind) }}</template></el-table-column>
          <el-table-column prop="notes" label="备注" min-width="160" /><el-table-column label="操作" min-width="170" fixed="right"><template #default="{ row }"><el-button size="small" @click="openHistory(row)">价格历史</el-button><el-button v-if="canManage" size="small" @click="openArchive(row)">编辑</el-button></template></el-table-column>
        </el-table>
        <el-table v-else :data="rows" border stripe :empty-text="activeTab === 'freight' ? '暂无货运公司' : '暂无供应商'">
          <el-table-column prop="code" label="编码" min-width="130" /><el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column :prop="activeTab === 'freight' ? 'contact' : 'contact_alias'" label="联系人" min-width="130" /><el-table-column :prop="activeTab === 'freight' ? 'phone' : 'contact_phone'" label="电话" min-width="150" />
          <el-table-column prop="province" label="省份" width="100" /><el-table-column prop="city" label="城市" width="100" /><el-table-column prop="tax_percent" label="税率 (%)" width="110" align="right" />
          <el-table-column label="状态" width="100"><template #default="{ row }">{{ activeTab === 'freight' ? (row.is_active ? '启用' : '停用') : supplierStatusLabels[row.status] || row.status }}</template></el-table-column>
          <el-table-column v-if="activeTab === 'suppliers'" label="合作与账期" min-width="200"><template #default="{row}"><div>首次合作：{{row.first_cooperation_date || '未维护'}}</div><small>{{row.payment_term_days==null?'账期未维护':`${row.payment_term_days} 天`}} · {{termStartLabel(row.payment_term_start)}}</small></template></el-table-column>
          <el-table-column label="操作" width="320" fixed="right"><template #default="{ row }"><el-button size="small" @click="openArchive(row)">{{ canManage ? '编辑' : '详情' }}</el-button><el-button v-if="activeTab === 'freight'" size="small" type="primary" @click="freightCompany = row">渠道与报价</el-button><el-button v-if="activeTab === 'suppliers'" size="small" @click="contactSupplier = row">联系人账号</el-button><el-button v-if="activeTab === 'suppliers'" size="small" @click="notificationSupplier = row">订单通知群</el-button></template></el-table-column>
        </el-table>
      </div>
      <el-pagination class="pagination" background layout="total, sizes, prev, pager, next" :total="total" :current-page="pagination.page" :page-size="pagination.pageSize" :page-sizes="[20, 50, 100]" @current-change="changePage" @size-change="changePageSize" />
      </template>
    </template>

    <el-drawer v-model="orderOpen" :title="selectedOrder ? '采购单详情' : '新建采购草稿'" size="min(1120px, 96vw)" :before-close="closeOrder">
      <template v-if="orderOpen">
        <div class="order-heading"><div><strong>{{ selectedOrder?.number || '保存后自动生成系统单号' }}</strong><p class="muted">系统单号只读，备注单号可重复。{{ selectedOrder ? `当前版本 v${selectedOrder.version}` : '' }}</p></div><el-tag v-if="selectedOrder" :type="statusType(selectedOrder.status)">{{ statusLabels[selectedOrder.status] }}</el-tag></div>
        <el-alert v-if="selectedOrder && !selectedOrder.prices_complete" title="该草稿仍有缺失单价，请补齐并保存后确认。" type="warning" :closable="false" />
        <p v-if="selectedOrder?.supplier_terms" class="muted">供应商账期：{{selectedOrder.supplier_terms.days==null?'未维护':`${selectedOrder.supplier_terms.days} 天`}} · {{selectedOrder.supplier_terms.start_label || '未约定'}} · {{selectedOrder.supplier_terms.state==='frozen'?'采购确认时已冻结':selectedOrder.supplier_terms.state==='unrecorded'?'历史单据未记录约定':'当前档案参考，确认采购时冻结'}}</p>
        <el-form label-position="top" class="order-form" :disabled="busy">
          <div class="form-grid">
            <el-form-item label="供应商 *">
              <el-select v-model="orderForm.supplier_id" filterable remote :remote-method="searchSuppliers" :loading="options.suppliers.loading" :disabled="!canEditLines || isOperatingSource" placeholder="搜索供应商" aria-label="采购供应商" @change="changeOrderSupplier" @visible-change="ensureSuppliers">
                <el-option v-for="item in options.suppliers.rows" :key="item.id" :label="optionLabel(item)" :value="item.id" /><template #footer><el-button v-if="hasMoreOptions('suppliers')" link @click="loadMoreOptions('suppliers')">加载更多供应商</el-button></template>
              </el-select>
            </el-form-item>
            <el-form-item label="国家 *"><el-select v-model="orderForm.country_id" filterable remote :remote-method="searchCountries" :loading="options.countries.loading" :disabled="!canEditLines || isOperatingSource" placeholder="搜索国家" aria-label="采购国家" @visible-change="ensureCountries"><el-option v-for="item in options.countries.rows" :key="item.id" :label="optionLabel(item)" :value="item.id" /><template #footer><el-button v-if="hasMoreOptions('countries')" link @click="loadMoreOptions('countries')">加载更多国家</el-button></template></el-select></el-form-item>
            <el-form-item label="采购日期 *"><el-date-picker v-model="orderForm.order_date" type="date" value-format="YYYY-MM-DD" :disabled="!canEditLines" aria-label="采购日期" /></el-form-item>
            <el-form-item label="备注单号"><el-input v-model="orderForm.reference_number" :disabled="!canManage" maxlength="120" aria-label="备注单号" /></el-form-item>
          </div>
          <el-form-item label="备注"><el-input v-model="orderForm.notes" type="textarea" :rows="2" :disabled="!canManage" aria-label="采购备注" /></el-form-item>
        </el-form>
        <div class="section-heading"><h3>采购明细</h3><el-button v-if="canEditLines && selectedOrder?.source_kind !== 'import' && !isOperatingSource" size="small" @click="addLine">添加 SKU</el-button></div>
        <p v-if="selectedOrder?.source_kind === 'import' && canEditLines" class="muted">导入明细保留原始 Excel 行号；新增商品请另建采购单。</p>
        <div class="table-scroll">
          <el-table :data="orderForm.lines" border empty-text="添加 SKU 或导入采购草稿">
            <el-table-column type="index" label="行" width="50" />
            <el-table-column label="SKU / 商品" min-width="250"><template #default="{ row }"><el-select v-if="canEditLines && !isOperatingSource" v-model="row.sku_id" filterable remote :remote-method="searchSkus" :loading="options.skus.loading" placeholder="搜索新旧 SKU 编码" aria-label="采购 SKU" @change="selectOrderSku(row)" @visible-change="ensureSkus"><el-option v-for="item in options.skus.rows" :key="item.id" :label="skuLabel(item)" :value="item.id" /><template #footer><el-button v-if="hasMoreOptions('skus')" link @click="loadMoreOptions('skus')">加载更多 SKU</el-button></template></el-select><DocumentSkuV2 v-if="row.sku_id" :sku="row.sku" :legacy-sku-code="row.legacy_sku_code" /><small class="line-name">{{ row.name }}</small></template></el-table-column>
            <el-table-column label="商品图片与规格" min-width="390"><template #default="{ row }"><PurchaseProductPreviewV2 v-if="row.sku_id" :order-id="selectedOrder?.status === 'confirmed' ? selectedOrder.id : null" :sku-id="row.sku_id" :sku="row.sku" :legacy-sku-code="row.legacy_sku_code" :product-details="row.product_details || {}" /></template></el-table-column>
            <el-table-column label="数量 *" width="150"><template #default="{ row }"><el-input-number v-if="canEditLines && !isOperatingSource" v-model="row.quantity" :min="1" :precision="0" :controls="false" aria-label="采购数量" /><span v-else>{{ row.quantity }}</span></template></el-table-column>
            <el-table-column label="采购单价" width="160"><template #default="{ row }"><el-input-number v-if="canEditLines" v-model="row.unit_price" :min="0" :precision="4" :controls="false" placeholder="待补" aria-label="采购单价" @change="row.price_defaulted = false" /><span v-else>{{ money(row.unit_price) }}</span></template></el-table-column>
            <el-table-column label="供应商参考价" width="140" align="right"><template #default="{ row }">{{ money(row.supplier_reference_price) }}</template></el-table-column>
            <el-table-column label="商品参考价" width="130" align="right"><template #default="{ row }">{{ money(row.product_reference_price) }}</template></el-table-column>
            <el-table-column label="金额" width="140" align="right"><template #default="{ row }">{{ money(lineAmount(row)) }}</template></el-table-column>
            <el-table-column v-if="canEditLines && !isOperatingSource" label="操作" width="80"><template #default="{ $index }"><el-button link type="danger" @click="orderForm.lines.splice($index, 1)">移除</el-button></template></el-table-column>
          </el-table>
        </div>
        <p class="muted">{{ orderForm.lines.length }} 行 · 共 {{ draftTotals.quantity }} 件 · 已有单价金额 {{ money(draftTotals.amount) }} <span v-if="draftTotals.missing">· {{ draftTotals.missing }} 行待补单价</span></p>
        <p v-if="selectedOrder?.status === 'confirmed'" class="muted">采购单已确认。请在“供应商发货单”跟进发货，在“集货发运与入库”跟进物流和收货。下方可查看后台订单通知进度。</p>
        <p v-if="isOperatingSource && canEditLines" class="muted">运营来源采购单可修改单价、备注与日期；商品和数量固定，需调整数量时请取消后重新拆分。</p>
        <p v-if="formError" role="alert" class="form-error">{{ formError }}</p>
        <template v-if="selectedOrder"><div class="download-actions"><el-button @click="downloadOrder('excel')" :loading="busy">下载采购 Excel</el-button><el-button @click="downloadOrder('labels')" :loading="busy">下载 SKU 标签 PDF</el-button></div><p class="muted">Excel 包含采购单、发货数量填写和箱号信息填写三张表；箱号信息作为线下附件填写。</p></template>
        <OrderNotificationV2 v-if="selectedOrder?.status === 'confirmed'" :key="selectedOrder.id" :order-id="selectedOrder.id" :version="selectedOrder.version" />
      </template>
        <template #footer v-if="orderOpen">
          <div class="drawer-actions">
            <el-button @click="orderOpen = false" :disabled="busy">关闭</el-button>
            <el-button v-if="canManage" type="primary" :loading="busy" :disabled="referencesLoading || referenceRefreshFailed" @click="saveOrder">{{ canEditLines ? '保存草稿' : '保存备注单号与备注' }}</el-button>
            <el-button v-if="canManage && selectedOrder?.status === 'draft'" type="success" :disabled="busy || referencesLoading || isOrderDirty || !selectedOrder.prices_complete" @click="actOnOrder('confirm')">确认采购</el-button>
            <el-button v-if="canManage && selectedOrder?.status === 'draft'" type="danger" plain :disabled="busy || isOrderDirty" @click="actOnOrder('cancel')">取消采购</el-button>
          </div><p v-if="selectedOrder?.status === 'draft' && isOrderDirty" class="muted">保存修改后可确认或取消采购。</p>
        </template>
    </el-drawer>

    <el-dialog v-model="archiveOpen" :title="archiveTitle" width="min(780px, 96vw)" class="sc2-scroll-dialog" top="4vh" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
      <el-form label-position="top" :disabled="!canManage || busy" class="archive-form">
        <template v-if="archiveKind === 'prices'">
          <div class="form-grid">
            <el-form-item label="供应商 *"><el-select v-model="archiveForm.supplier_id" filterable remote :remote-method="searchSuppliers" :loading="options.suppliers.loading" :disabled="!!archiveRecord" placeholder="搜索供应商" aria-label="报价供应商" @visible-change="ensureSuppliers" @change="changePriceSupplier"><el-option v-for="item in options.suppliers.rows" :key="item.id" :label="optionLabel(item)" :value="item.id" /><template #footer><el-button v-if="hasMoreOptions('suppliers')" link @click="loadMoreOptions('suppliers')">加载更多供应商</el-button></template></el-select></el-form-item>
            <el-form-item label="SKU *"><el-select v-model="archiveForm.sku_id" filterable remote :remote-method="searchPriceSkus" :loading="options.skus.loading" :disabled="!!archiveRecord" placeholder="搜索 SKU" aria-label="报价 SKU" @visible-change="ensurePriceSkus"><el-option v-for="item in options.skus.rows" :key="item.id" :label="skuLabel(item)" :value="item.id" /><template #footer><el-button v-if="hasMoreOptions('skus')" link @click="loadMoreOptions('skus')">加载更多 SKU</el-button></template></el-select></el-form-item>
            <el-form-item label="单价 *"><el-input-number v-model="archiveForm.unit_price" :min="0" :precision="4" :controls="false" aria-label="供应商单价" /></el-form-item>
            <el-form-item label="生效日期 *"><el-date-picker v-model="archiveForm.effective_date" type="date" value-format="YYYY-MM-DD" aria-label="报价生效日期" /></el-form-item>
          </div>
          <el-form-item label="备注"><el-input v-model="archiveForm.notes" type="textarea" :rows="3" aria-label="报价备注" /></el-form-item>
        </template>
        <div v-else class="form-grid">
          <el-form-item v-for="field in archiveFields" :key="field.key" :label="field.label" :class="{ 'span-all': field.type === 'textarea' }">
            <el-select v-if="field.type === 'status'" v-model="archiveForm[field.key]" :aria-label="field.label"><el-option v-for="(label, value) in supplierStatusLabels" :key="value" :label="label" :value="value" /></el-select>
            <el-switch v-else-if="field.type === 'boolean'" v-model="archiveForm[field.key]" active-text="启用" inactive-text="停用" :aria-label="field.label" />
            <el-input-number v-else-if="field.type === 'number'" v-model="archiveForm[field.key]" :min="0" :max="field.key === 'tax_percent' ? 100 : undefined" :precision="field.key === 'tax_percent' ? 2 : 4" :controls="false" :aria-label="field.label" />
            <el-input v-else v-model="archiveForm[field.key]" :type="field.type === 'textarea' ? 'textarea' : 'text'" :rows="2" :aria-label="field.label" />
          </el-form-item>
          <SupplierTermsFieldsV2 v-if="archiveKind === 'suppliers'" :form="archiveForm" :disabled="!canManage || busy" />
        </div>
      </el-form>
      <p v-if="archiveError" role="alert" class="form-error">{{ archiveError }}</p>
      <template #footer><el-button :disabled="busy" @click="archiveOpen = false">关闭</el-button><el-button v-if="canManage" type="primary" :loading="busy" @click="saveArchive">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="historyOpen" title="供应商价格历史" width="min(920px, 96vw)">
      <p>{{ historyTitle }}</p><el-alert v-if="historyError" :title="historyError" type="error" :closable="false" />
      <el-table v-loading="historyLoading" :data="historyRows" border empty-text="暂无价格历史"><el-table-column prop="created_at" label="记录时间" min-width="180" /><el-table-column prop="unit_price" label="单价" width="120" /><el-table-column prop="effective_date" label="生效日期" width="120" /><el-table-column label="来源" width="130"><template #default="{ row }">{{ sourceLabel(row.source_kind) }}</template></el-table-column><el-table-column prop="source_order_id" label="来源采购单 ID" width="140" /><el-table-column prop="source_order_version" label="采购版本" width="100" /><el-table-column prop="notes" label="备注" min-width="180" /></el-table>
      <el-pagination class="pagination" layout="total, prev, pager, next" :total="historyTotal" :current-page="historyPage" :page-size="20" @current-change="changeHistoryPage" />
    </el-dialog>

    <el-dialog v-model="importOpen" title="Excel 采购导入" width="min(1080px, 96vw)" :close-on-click-modal="false">
      <p class="muted">先预览并校验，再提交为草稿；导入不会自动确认采购。</p>
      <div class="import-picker"><input type="file" accept=".xlsx" aria-label="选择采购 Excel" :disabled="busy" @change="selectImportFile" /><el-button :disabled="!importFile || busy || !canManage" :loading="busy" @click="previewImportFile">预览校验</el-button></div>
      <el-alert v-if="importError" :title="importError" type="error" :closable="false" />
      <template v-if="importJob">
        <p>{{ importJob.filename }} · {{ importJob.preview?.rows_count || 0 }} 行 · {{ importJob.preview?.groups_count || 0 }} 张采购单 · {{ importJob.preview?.total_quantity || 0 }} 件 · 已有单价金额 {{ money(importJob.preview?.total_amount) }}</p>
        <el-alert v-if="importJob.committed_at" :title="`已生成 ${importJob.order_ids?.length || 0} 张采购草稿，可在采购单页补充单价并确认。`" type="success" :closable="false" />
        <el-alert v-else-if="importJob.preview?.missing_prices_count" :title="`${importJob.preview.missing_prices_count} 行缺少单价，提交后须补齐才能确认。`" type="warning" :closable="false" />
        <el-table v-if="importJob.preview?.errors?.length" :data="importJob.preview.errors" border class="preview-table"><el-table-column prop="row" label="Excel 行" width="100" /><el-table-column prop="field" label="字段" width="140" /><el-table-column prop="message" label="错误" min-width="300" /></el-table>
        <el-table :data="importJob.preview?.groups || []" border class="preview-table"><el-table-column prop="supplier_name" label="供应商" min-width="180" /><el-table-column prop="country_name" label="国家" min-width="120" /><el-table-column prop="reference_number" label="备注单号" min-width="160" /><el-table-column prop="lines_count" label="明细行" width="100" /><el-table-column prop="total_quantity" label="数量" width="100" /><el-table-column prop="total_amount" label="已有单价金额" min-width="140" /></el-table>
      </template>
      <template #footer><el-button :disabled="busy" @click="importOpen = false">关闭</el-button><el-button v-if="canManage" type="primary" :loading="busy" :disabled="!importJob?.preview?.valid || !!importJob?.committed_at" @click="commitImportFile">提交为采购草稿</el-button></template>
    </el-dialog>
    <SupplierContactsV2 v-if="contactSupplier" :supplier="contactSupplier" :can-manage="canManage" @close="contactSupplier = null" />
    <el-drawer :model-value="!!freightCompany" :title="`${freightCompany?.name || ''} · 渠道与报价`" size="min(1100px,96vw)" @close="freightCompany=null"><FreightChannelsV2 v-if="freightCompany" :key="freightCompany.id" :company="freightCompany"/></el-drawer>
    <el-drawer v-model="notificationBindingOpen" title="供应商订单通知群" size="min(780px, 96vw)">
      <SupplierNotificationBindingV2 v-if="notificationSupplier" :key="notificationSupplier.id" :supplier-id="notificationSupplier.id" :supplier-name="notificationSupplier.name" />
    </el-drawer>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import '../../styles/supplyCollaboration.css';
import FreightChannelsV2 from '../../components/supply-chain/FreightChannelsV2.vue';
import SupplierTermsFieldsV2 from '../../components/supply-chain/SupplierTermsFieldsV2.vue';
import PurchaseProductPreviewV2 from '../../components/supply-chain/PurchaseProductPreviewV2.vue';
import DocumentSkuV2 from '../../components/supply-chain/DocumentSkuV2.vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import SupplierContactsV2 from '../../components/supply-chain/SupplierContactsV2.vue';
import SupplierNotificationBindingV2 from '../../components/supply-chain/SupplierNotificationBindingV2.vue';
import OrderNotificationV2 from '../../components/supply-chain/OrderNotificationV2.vue';
import OperatingSplitV2 from '../../components/supply-chain/OperatingSplitV2.vue';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import * as api from '../../api/supplyChainV2';

const props=defineProps({archiveKind:{type:String,default:'',validator:value=>['','suppliers','prices','freight'].includes(value)}});
const isArchivePage=computed(()=>Boolean(props.archiveKind));
const pageTitle=computed(()=>({suppliers:'供应商档案',prices:'供应商价格',freight:'货运公司'})[props.archiveKind]||'采购协同');
const archivePath=computed(()=>({suppliers:'/master-data/suppliers',prices:'/master-data/supplier-prices',freight:'/master-data/freight-companies'})[props.archiveKind]||'/supply-chain/purchase-orders');
const auth = useAuthStore();
const contactSupplier = ref(null);
const notificationSupplier = ref(null);
const notificationBindingOpen = computed({ get: () => Boolean(notificationSupplier.value), set: value => { if (!value) notificationSupplier.value = null; } });
const canView = computed(() => !auth.authorizationStale && (auth.hasPermission('supply.v2.view') || canAccessPath(auth.currentUser, archivePath.value)));
const canManage = computed(() => canView.value && auth.hasPermission('supply.v2.manage'));
const activeTab = ref(props.archiveKind || 'orders');
const filters = reactive({ search: '', status: '', source_kind: '', supplier_id: null });
const pagination = reactive({ page: 1, pageSize: 20 });
const rows = ref([]), total = ref(0), loading = ref(false), busy = ref(false), errorMessage = ref('');
const statusLabels = { draft: '草稿', confirmed: '已确认', cancelled: '已取消' };
const supplierStatusLabels = { active: '合作中', trial: '试合作', inactive: '已停用' };
const today = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const money = value => value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const sourceLabel = value => ({ manual: '手工', operating: '运营订货单', excel: 'Excel 导入', import: 'Excel 导入', excel_import: 'Excel 导入', purchase_confirm: '采购确认', purchase_order: '采购单保存', confirmed_order: '采购确认' }[value] || value || '—');
const statusType = value => ({ draft: 'warning', confirmed: 'success', cancelled: 'info' }[value] || 'info');
const optionLabel = item => `${item.code ? `${item.code} · ` : ''}${item.name}`;
const skuLabel = item => item.sku + (item.legacy_sku_code ? ` · 旧 ${item.legacy_sku_code}` : '') + ` · ${item.name || ''}`;
const nullableNumber = value => value === null || value === undefined || value === '' ? null : Number(value);
const collection = response => ({ rows: Array.isArray(response.data) ? response.data : response.data?.results || response.data?.items || [], count: Number(response.count ?? response.data?.count ?? 0) });
const failureMessage = response => {
  const details = response?.data?.errors || response?.data?.detail;
  const text = typeof details === 'string' ? details : Array.isArray(details) ? details.map(item => typeof item === 'string' ? item : item.message).filter(Boolean).join('；') : '';
  return text || response?.message || '请求失败，请重试。';
};
let listSequence = 0;
async function load() {
  if (!canView.value) return;
  if (activeTab.value === 'operating') {
    ++listSequence; loading.value = false; errorMessage.value = '';
    return;
  }
  const sequence = ++listSequence, tab = activeTab.value;
  loading.value = true; errorMessage.value = '';
  const params = { search: filters.search.trim(), limit: pagination.pageSize, offset: (pagination.page - 1) * pagination.pageSize };
  if (tab === 'orders') Object.assign(params, { status: filters.status, source_kind: filters.source_kind });
  if (tab === 'prices' && filters.supplier_id) params.supplier_id = filters.supplier_id;
  const fetchers = { orders: api.fetchPurchaseOrders, suppliers: api.fetchSuppliers, prices: api.fetchSupplierPrices, freight: api.fetchFreightCompanies };
  try {
    const response = await fetchers[tab](params);
    if (sequence !== listSequence) return;
    if (!response?.success) { rows.value = []; total.value = 0; errorMessage.value = failureMessage(response); return; }
    const result = collection(response); rows.value = result.rows; total.value = result.count;
  } catch (error) { if (sequence === listSequence) { rows.value = []; total.value = 0; errorMessage.value = error.message || '请求失败，请重试。'; } }
  finally { if (sequence === listSequence) loading.value = false; }
}
function applyFilters() { pagination.page = 1; return load(); }
function resetFilters() { Object.assign(filters, { search: '', status: '', source_kind: '', supplier_id: null }); return applyFilters(); }
function changeTab() { rows.value = []; if (activeTab.value === 'operating') return load(); return resetFilters(); }
function changePage(page) { pagination.page = page; return load(); }
function changePageSize(size) { pagination.pageSize = size; return applyFilters(); }

const options = reactive(Object.fromEntries(['suppliers', 'countries', 'skus'].map(kind => [kind, { rows: [], count: 0, offset: 0, search: '', supplier_id: null, loading: false, sequence: 0 }])));
function rememberOption(kind, item) {
  if (item?.id && !options[kind].rows.some(row => row.id === item.id)) options[kind].rows.push(item);
}
async function loadOptions(kind, search = '', append = false, supplierId = null) {
  const state = options[kind], sequence = ++state.sequence;
  state.loading = true;
  const offset = append ? state.offset : 0;
  if (!append) { state.search = search; state.supplier_id = supplierId; }
  try {
    const response = await api.fetchSupplyOptions({ kind, search, limit: 50, offset, ...(kind === 'skus' && supplierId ? { supplier_id: supplierId } : {}) });
    if (state.sequence !== sequence) return;
    if (!response?.success) { ElMessage.error(failureMessage(response)); return; }
    const result = collection(response), retained = [];
    if (!append) {
      const ids = kind === 'suppliers' ? [orderForm.supplier_id, archiveForm.supplier_id, filters.supplier_id] : kind === 'countries' ? [orderForm.country_id] : [...orderForm.lines.map(line => line.sku_id), archiveForm.sku_id];
      retained.push(...state.rows.filter(item => ids.includes(item.id)));
    }
    const merged = [...(append ? state.rows : retained), ...result.rows];
    state.rows = [...new Map(merged.map(item => [item.id, item])).values()];
    state.offset = offset + result.rows.length; state.count = result.count;
  } finally { if (state.sequence === sequence) state.loading = false; }
}
const hasMoreOptions = kind => options[kind].offset < options[kind].count;
const loadMoreOptions = kind => { const state = options[kind]; return state.loading ? undefined : loadOptions(kind, state.search, true, state.supplier_id); };
const searchSuppliers = search => loadOptions('suppliers', search);
const searchCountries = search => loadOptions('countries', search);
const searchSkus = search => loadOptions('skus', search, false, orderForm.supplier_id);
const searchPriceSkus = search => loadOptions('skus', search, false, archiveForm.supplier_id);
const ensureSuppliers = open => open && !options.suppliers.offset && searchSuppliers('');
const ensureCountries = open => open && !options.countries.offset && searchCountries('');
const ensureSkus = open => open && searchSkus(options.skus.search);
const ensurePriceSkus = open => open && searchPriceSkus(options.skus.search);

// Retain an action's key while the network outcome is uncertain. A changed
// payload is a new action; a retry of the same payload uses the same key.
const pendingActions = new Map();
async function mutate(slot, payload, execute, showError) {
  if (!canManage.value || busy.value) return null;
  const fingerprint = JSON.stringify(payload);
  let action = pendingActions.get(slot);
  if (!action || action.fingerprint !== fingerprint) { action = { fingerprint, key: api.createIdempotencyKey() }; pendingActions.set(slot, action); }
  busy.value = true;
  try {
    const response = await execute(action.key);
    if (response?.success) { pendingActions.delete(slot); return response.data; }
    const uncertain = !response?.http_status || response.http_status >= 500;
    if (!uncertain) pendingActions.delete(slot);
    showError(`${failureMessage(response)}${uncertain ? ' 结果尚未确认，请用相同内容重试；系统会复用本次请求标识。' : response.http_status === 409 ? ' 请关闭后重新打开记录，获取最新版本。' : ''}`);
    return null;
  } catch (error) { showError(`${error.message || '网络异常'}。结果尚未确认，请用相同内容重试。`); return null; }
  finally { busy.value = false; }
}

const orderOpen = ref(false), selectedOrder = ref(null), formError = ref(''), referencesLoading = ref(false), referenceRefreshFailed = ref(false);
const orderForm = reactive({ supplier_id: null, country_id: null, reference_number: '', order_date: today(), notes: '', lines: [] });
const savedOrderPayload = ref('');
const canEditLines = computed(() => canManage.value && (!selectedOrder.value || selectedOrder.value.status === 'draft'));
const isOperatingSource = computed(() => selectedOrder.value?.source_kind === 'operating');
function orderPayload() { return { supplier_id: orderForm.supplier_id, country_id: orderForm.country_id, reference_number: orderForm.reference_number.trim(), order_date: orderForm.order_date, notes: orderForm.notes, lines: orderForm.lines.map(line => ({ sku_id: line.sku_id, quantity: Number(line.quantity), unit_price: nullableNumber(line.unit_price), ...(selectedOrder.value?.source_kind === 'import' ? { import_row_number: line.import_row_number } : {}) })) }; }
const isOrderDirty = computed(() => JSON.stringify(orderPayload()) !== savedOrderPayload.value);
const lineAmount = line => nullableNumber(line.unit_price) === null ? null : Number(line.quantity || 0) * Number(line.unit_price);
const draftTotals = computed(() => orderForm.lines.reduce((sum, line) => ({ quantity: sum.quantity + Number(line.quantity || 0), amount: sum.amount + Number(lineAmount(line) || 0), missing: sum.missing + (nullableNumber(line.unit_price) === null ? 1 : 0) }), { quantity: 0, amount: 0, missing: 0 }));
function setOrder(order) {
  ++supplierRefreshSequence; referencesLoading.value = false;
  selectedOrder.value = order;
  Object.assign(orderForm, { supplier_id: order?.supplier_id || null, country_id: order?.country_id || null, reference_number: order?.reference_number || '', order_date: order?.order_date || today(), notes: order?.notes || '', lines: (order?.lines || []).map(line => ({ ...line, quantity: Number(line.quantity), unit_price: nullableNumber(line.unit_price), price_defaulted: false })) });
  if (order) {
    rememberOption('suppliers', { id: order.supplier_id, name: order.supplier_name });
    rememberOption('countries', { id: order.country_id, code: order.country_code, name: order.country_name });
    for (const line of order.lines || []) rememberOption('skus', { id: line.sku_id, sku: line.sku, legacy_sku_code: line.legacy_sku_code, name: line.name, product_reference_price: line.product_reference_price, supplier_reference_price: line.supplier_reference_price, product_details: line.product_details });
  }
  savedOrderPayload.value = JSON.stringify(orderPayload()); formError.value = ''; referenceRefreshFailed.value = false;
}
function openCreate() { if (!canManage.value || busy.value) return; ++detailSequence; setOrder(null); orderOpen.value = true; searchSuppliers(''); searchCountries(''); }
let detailSequence = 0;
async function openDetail(row) {
  if (!canView.value || busy.value) return;
  const sequence = ++detailSequence;
  const response = await api.fetchPurchaseOrder(row.id);
  if (sequence !== detailSequence) return;
  if (!response?.success) { ElMessage.error(failureMessage(response)); return; }
  setOrder(response.data); orderOpen.value = true;
}
function closeOrder(done) { if (!busy.value) done(); }
function addLine() { if (canEditLines.value && selectedOrder.value?.source_kind !== 'import') orderForm.lines.push({ sku_id: null, sku: '', legacy_sku_code: '', name: '', product_details: {}, quantity: 1, unit_price: null, product_reference_price: null, supplier_reference_price: null, price_defaulted: true }); }
function selectOrderSku(line) {
  const item = options.skus.rows.find(row => row.id === line.sku_id);
  if (!item) return;
  Object.assign(line, { sku: item.sku, legacy_sku_code: item.legacy_sku_code || '', name: item.name, product_details: item.product_details || {}, product_reference_price: item.product_reference_price, supplier_reference_price: item.supplier_reference_price, unit_price: nullableNumber(item.supplier_reference_price ?? item.product_reference_price), price_defaulted: true });
}
let supplierRefreshSequence = 0;
async function findSkuReference(line, supplierId) {
  let offset = 0;
  do {
    const response = await api.fetchSupplyOptions({ kind: 'skus', search: line.sku, supplier_id: supplierId, limit: 50, offset });
    if (!response?.success) throw new Error(failureMessage(response));
    const result = collection(response), found = result.rows.find(item => item.id === line.sku_id);
    if (found) return found;
    offset += result.rows.length;
    if (!result.rows.length || offset >= result.count) return null;
  } while (true);
}
async function changeOrderSupplier() {
  const sequence = ++supplierRefreshSequence, supplierId = orderForm.supplier_id;
  referencesLoading.value = true; formError.value = ''; referenceRefreshFailed.value = false;
  try {
    const lines = [...orderForm.lines];
    const references = await Promise.all(lines.filter(line => line.sku_id).map(async line => ({ line, item: await findSkuReference(line, supplierId) })));
    if (sequence !== supplierRefreshSequence) return;
    for (const { line, item } of references) {
      if (!orderForm.lines.includes(line)) continue;
      line.supplier_reference_price = item?.supplier_reference_price ?? null;
      line.product_reference_price = item?.product_reference_price ?? null;
      if (item) { line.legacy_sku_code = item.legacy_sku_code || ''; line.product_details = item.product_details || {}; }
      if (line.price_defaulted) line.unit_price = nullableNumber(item?.supplier_reference_price ?? item?.product_reference_price);
      if (item) { options.skus.rows = options.skus.rows.filter(row => row.id !== item.id); rememberOption('skus', item); }
    }
    await searchSkus('');
  } catch (error) { if (sequence === supplierRefreshSequence) { referenceRefreshFailed.value = true; formError.value = `参考价刷新失败：${error.message}。请重新选择供应商后保存。`; } }
  finally { if (sequence === supplierRefreshSequence) referencesLoading.value = false; }
}
function validateOrder() {
  if (!orderForm.supplier_id || !orderForm.country_id || !orderForm.order_date) return '请选择供应商、国家与采购日期。';
  if (!orderForm.lines.length) return '至少添加一条采购明细。';
  if (orderForm.lines.some(line => !line.sku_id || !Number.isInteger(Number(line.quantity)) || Number(line.quantity) < 1)) return '每行须选择 SKU，并填写大于 0 的整数数量。';
  if (orderForm.order_date > today()) return '采购日期不能晚于今天。';
  if (orderForm.lines.some(line => nullableNumber(line.unit_price) !== null && (!Number.isFinite(Number(line.unit_price)) || Number(line.unit_price) < 0))) return '单价须为大于或等于 0 的数字；缺失时可留空。';
  return '';
}
async function saveOrder() {
  if (!canManage.value || referencesLoading.value || referenceRefreshFailed.value) return;
  formError.value = canEditLines.value ? validateOrder() : '';
  if (formError.value) return;
  const selected = selectedOrder.value;
  const data = canEditLines.value ? { ...orderPayload(), ...(selected ? { expected_version: selected.version } : {}) } : { reference_number: orderForm.reference_number.trim(), notes: orderForm.notes, expected_version: selected.version };
  const saved = await mutate(`order-save-${selected?.id || 'new'}`, data, key => selected ? canEditLines.value ? api.updatePurchaseOrder(selected.id, data, key) : api.updatePurchaseOrderMetadata(selected.id, data, key) : api.createPurchaseOrder(data, key), message => { formError.value = message; });
  if (saved) { setOrder(saved); ElMessage.success('采购单已保存。'); await load(); }
}
async function actOnOrder(action) {
  const order = selectedOrder.value;
  if (!canManage.value || !order || order.status !== 'draft' || isOrderDirty.value || (action === 'confirm' && !order.prices_complete)) return;
  try { await ElMessageBox.confirm(action === 'confirm' ? '确认后固定采购明细，并创建后台通知记录。实际投递由通知通道和系统开关控制。' : '取消该采购草稿？', action === 'confirm' ? '确认采购' : '取消采购', { confirmButtonText: '确定', cancelButtonText: '返回', type: 'warning' }); } catch { return; }
  const data = { expected_version: order.version };
  const saved = await mutate(`order-${action}-${order.id}`, data, key => action === 'confirm' ? api.confirmPurchaseOrder(order.id, data, key) : api.cancelPurchaseOrder(order.id, data, key), message => { formError.value = message; });
  if (saved) { setOrder(saved); ElMessage.success(action === 'confirm' ? '采购已确认，已创建后台通知记录。' : '采购已取消。'); await load(); }
}
async function downloadTemplate() { if (canView.value) { const response = await api.downloadImportTemplate(); if (!response?.success) ElMessage.error(failureMessage(response)); } }
async function downloadOrder(kind) { if (!canView.value || !selectedOrder.value) return; const order = selectedOrder.value; const response = await (kind === 'excel' ? api.downloadPurchaseExcel(order.id, order.number) : api.downloadPurchaseLabels(order.id, order.number)); if (!response?.success) ElMessage.error(failureMessage(response)); }

const supplierFields = [
  { key: 'code', label: '供应商编码 *' }, { key: 'name', label: '供应商名称 *' }, { key: 'contact_alias', label: '联系人' }, { key: 'contact_phone', label: '电话' }, { key: 'contact_email', label: '邮箱' }, { key: 'status', label: '合作状态', type: 'status' }, { key: 'province', label: '省份' }, { key: 'city', label: '城市' }, { key: 'factory_address', label: '工厂地址', type: 'textarea' }, { key: 'loading_address', label: '装柜地址', type: 'textarea' }, { key: 'tax_percent', label: '税费点数 (%)', type: 'number' }, { key: 'notes', label: '备注', type: 'textarea' }
];
const freightFields = [
  { key: 'code', label: '货运公司编码 *' }, { key: 'name', label: '货运公司名称 *' }, { key: 'contact', label: '联系人' }, { key: 'phone', label: '电话' }, { key: 'province', label: '省份' }, { key: 'city', label: '城市' }, { key: 'address', label: '地址', type: 'textarea' }, { key: 'shipping_marks', label: '唛头', type: 'textarea' }, { key: 'fee_per_cbm', label: '每立方米费用（可留空）', type: 'number' }, { key: 'tax_percent', label: '税率 (%)', type: 'number' }, { key: 'is_active', label: '使用状态', type: 'boolean' }, { key: 'notes', label: '备注', type: 'textarea' }
];
const archiveOpen = ref(false), archiveKind = ref('suppliers'), archiveRecord = ref(null), archiveForm = reactive({}), archiveError = ref(''), freightCompany=ref(null);
const termStartLabel=value=>({unspecified:'未约定',shipment_date:'发货日起算',collection_arrival:'集货到仓日起算',warehouse_arrival:'目的仓到仓日起算',reconciliation_date:'对账确认日起算'})[value]||'未约定';
const archiveFields = computed(() => archiveKind.value === 'freight' ? freightFields : supplierFields);
const archiveTitle = computed(() => `${archiveRecord.value ? canManage.value ? '编辑' : '查看' : '新增'}${{ suppliers: '供应商档案', freight: '货运公司', prices: '供应商报价' }[archiveKind.value]}`);
function openArchive(row = null) {
  if (!canView.value || busy.value || (!row && !canManage.value)) return;
  archiveKind.value = activeTab.value; archiveRecord.value = row; archiveError.value = '';
  for (const key of Object.keys(archiveForm)) delete archiveForm[key];
  if (archiveKind.value === 'prices') {
    Object.assign(archiveForm, { supplier_id: row?.supplier_id || filters.supplier_id || null, sku_id: row?.sku_id || null, unit_price: nullableNumber(row?.unit_price), effective_date: row?.effective_date || today(), notes: row?.notes || '' });
    if (row) { rememberOption('suppliers', { id: row.supplier_id, name: row.supplier_name }); rememberOption('skus', { id: row.sku_id, sku: row.sku, name: row.name }); }
    searchSuppliers('');
  } else {
    for (const field of archiveFields.value) { const value = row?.[field.key] ?? (field.type === 'boolean' ? true : field.key === 'status' ? 'active' : field.key === 'tax_percent' ? 0 : field.type === 'number' ? null : ''); archiveForm[field.key] = field.type === 'number' ? nullableNumber(value) : value; }
    if(archiveKind.value==='suppliers')Object.assign(archiveForm,{first_cooperation_date:row?.first_cooperation_date||null,payment_term_days:row?.payment_term_days??null,payment_term_start:row?.payment_term_start||'unspecified'});
  }
  archiveOpen.value = true;
}
function changePriceSupplier() { archiveForm.sku_id = null; return searchPriceSkus(''); }
async function saveArchive() {
  if (!canManage.value) return;
  archiveError.value = '';
  let data;
  if (archiveKind.value === 'prices') {
    if (!archiveForm.supplier_id || !archiveForm.sku_id || nullableNumber(archiveForm.unit_price) === null || !Number.isFinite(Number(archiveForm.unit_price)) || Number(archiveForm.unit_price) < 0 || !archiveForm.effective_date) { archiveError.value = '请选择供应商、SKU、生效日期，并填写有效单价。'; return; }
    if (archiveForm.effective_date > today()) { archiveError.value = '生效日期不能晚于今天。'; return; }
    data = { ...archiveForm, unit_price: Number(archiveForm.unit_price), expected_version: archiveRecord.value?.version || 0 };
  } else {
    if (!archiveForm.code.trim() || !archiveForm.name.trim()) { archiveError.value = '编码与名称为必填项。'; return; }
    if (nullableNumber(archiveForm.tax_percent) === null || Number(archiveForm.tax_percent) < 0 || Number(archiveForm.tax_percent) > 100) { archiveError.value = '税率须在 0 到 100 之间。'; return; }
    data = Object.fromEntries(archiveFields.value.map(field => [field.key, field.type === 'number' ? nullableNumber(archiveForm[field.key]) : archiveForm[field.key]]));
    if(archiveKind.value==='suppliers')Object.assign(data,{first_cooperation_date:archiveForm.first_cooperation_date||null,payment_term_days:nullableNumber(archiveForm.payment_term_days),payment_term_start:archiveForm.payment_term_start||'unspecified'});
    data.code = data.code.trim(); data.name = data.name.trim();
    if (archiveRecord.value) data.expected_version = archiveRecord.value.version;
  }
  const kind = archiveKind.value, record = archiveRecord.value;
  const saved = await mutate(`archive-${kind}-${record?.id || 'new'}`, data, key => kind === 'prices' ? api.saveSupplierPrice(data, key) : kind === 'suppliers' ? record ? api.updateSupplier(record.id, data, key) : api.createSupplier(data, key) : record ? api.updateFreightCompany(record.id, data, key) : api.createFreightCompany(data, key), message => { archiveError.value = message; });
  if (saved) { archiveOpen.value = false; ElMessage.success('档案已保存。'); await load(); }
}
const historyOpen = ref(false), historyRows = ref([]), historyLoading = ref(false), historyError = ref(''), historyTitle = ref(''), historyTotal = ref(0), historyPage = ref(1), historyPriceId = ref(null);
async function openHistory(row) {
  if (!canView.value) return;
  historyOpen.value = true; historyRows.value = []; historyTitle.value = `${row.supplier_name} · ${row.sku}`; historyPriceId.value = row.id; historyPage.value = 1; return loadHistory();
}
async function loadHistory() {
  historyLoading.value = true; historyError.value = '';
  try { const response = await api.fetchSupplierPriceHistory(historyPriceId.value, { limit: 20, offset: (historyPage.value - 1) * 20 }); if (!response?.success) { historyError.value = failureMessage(response); return; } const result = collection(response); historyRows.value = result.rows; historyTotal.value = result.count; }
  finally { historyLoading.value = false; }
}
function changeHistoryPage(page) { historyPage.value = page; return loadHistory(); }

const importOpen = ref(false), importFile = ref(null), importJob = ref(null), importError = ref(''), importSelectionId = ref('');
function openImport() { if (!canManage.value || busy.value) return; importOpen.value = true; importError.value = ''; }
function selectImportFile(event) { if (busy.value) return; importFile.value = event.target.files?.[0] || null; importSelectionId.value = api.createIdempotencyKey(); importJob.value = null; importError.value = ''; }
async function previewImportFile() {
  if (!canManage.value || !importFile.value) return;
  importError.value = ''; const file = importFile.value;
  if (!/\.xlsx$/i.test(file.name) || file.size > 5 * 1024 * 1024) { importError.value = '请选择 5MB 以内的 .xlsx 文件。'; return; }
  const payload = { selection: importSelectionId.value, filename: file.name, size: file.size, modified: file.lastModified };
  const job = await mutate('import-preview', payload, key => api.previewImport(file, key), message => { importError.value = message; });
  if (job) importJob.value = job;
}
async function commitImportFile() {
  const job = importJob.value;
  if (!canManage.value || !job?.preview?.valid || job.committed_at) return;
  importError.value = ''; const data = { expected_version: job.version };
  const saved = await mutate(`import-commit-${job.id}`, data, key => api.commitImport(job.id, data, key), message => { importError.value = message; });
  if (saved) { importJob.value = saved; activeTab.value = 'orders'; await resetFilters(); ElMessage.success('导入已提交为采购草稿。'); }
}
watch(()=>props.archiveKind,value=>{activeTab.value=value||'orders';contactSupplier.value=null;notificationSupplier.value=null;archiveOpen.value=false;changeTab();});
onMounted(load);
</script>

<style scoped>
.integration-notice, .error-notice { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0 18px; align-items: center; }
.filter-bar > .el-input { width: min(330px, 100%); }
.filter-bar > .el-select { width: 170px; }
.table-scroll { width: 100%; min-width: 0; overflow-x: auto; }
.pagination { margin-top: 18px; overflow-x: auto; padding-bottom: 8px; }
.muted { color: #64748b; font-size: 13px; line-height: 1.6; }
.price-missing, .line-name { display: block; font-size: 12px; color: #9a6700; margin-top: 4px; }
.line-name { color: #64748b; }
.order-heading, .section-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; }
.order-heading strong { font-size: 20px; color: #172033; }
.order-heading p { margin: 6px 0 0; }
.section-heading { align-items: center; margin-top: 16px; margin-bottom: 12px; }
.section-heading h3 { margin: 0; font-size: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }
.order-form { margin-top: 20px; }
.form-grid :deep(.el-select), .form-grid :deep(.el-date-editor), .form-grid :deep(.el-input-number), .table-scroll :deep(.el-input-number), .table-scroll :deep(.el-select) { width: 100%; }
.span-all { grid-column: 1 / -1; }
.drawer-actions, .download-actions, .import-picker { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.drawer-actions { justify-content: flex-end; }
.drawer-actions :deep(.el-button + .el-button), .download-actions :deep(.el-button + .el-button) { margin-left: 0; }
.download-actions { margin-top: 22px; }
.form-error { color: #b42318; font-size: 14px; line-height: 1.6; }
.import-picker { margin-bottom: 18px; }
.import-picker input { max-width: 100%; }
.preview-table { margin-top: 16px; }
@media (max-width: 680px) { .form-grid { grid-template-columns: 1fr; }.filter-bar > .el-input, .filter-bar > .el-select { width: 100%; }.order-heading { flex-wrap: wrap; }.drawer-actions { justify-content: flex-start; } }
</style>
