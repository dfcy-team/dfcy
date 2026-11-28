<template>
  <section aria-label="原始仓库账单解析" class="warehouse-bill-workspace">
    <input ref="billInput" class="bill-file-input" type="file" accept=".xlsx" aria-label="选择原始账单文件" :disabled="busy || active || pendingEdit" @change="upload" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon role="alert" />
    <el-alert v-if="feedback" :title="feedback" type="success" :closable="false" show-icon role="status" />
    <p v-if="uploadPercent !== null" role="status">上传中 {{ uploadPercent }}% · 上传完成后自动开始解析</p>
    <section v-if="!job" class="file-chooser" aria-label="等待选择账单">
      <h2>选择原始仓库账单</h2>
      <p>选择 Z:\处理费 中的原始 xlsx 文件，自动解析仓库处理费和其他处理费。</p>
      <p class="muted">每份最多 128MB，金额按原数字 CNY 记录。上传和解析只生成预览，不会自动登记费用。</p>
      <div class="upload-line"><el-button type="primary" :loading="busy" @click="chooseFile(false)">选择原始账单并解析</el-button><el-button :disabled="busy" @click="chooseFile(true)">新格式／已保存格式规则</el-button></div>
      <label class="history-label">继续核对已上传文件
        <el-select v-model="historyId" placeholder="选择最近上传的账单" aria-label="最近上传的原账单" :disabled="busy" @change="selectHistory">
          <el-option v-for="item in history" :key="item.id" :value="item.id" :label="`${item.file_name} · ${states[item.status] || item.status}`" />
        </el-select>
      </label>
      <p class="muted">新格式或已有格式规则：上传后进入“格式配置”，选择规则或配置工作表，再重新预览。</p>
    </section>
    <section v-else-if="formatVisible && filePolicy" aria-label="账单格式配置" class="format-workspace">
      <div class="job-state"><h2>格式配置</h2><span>{{ job.file_name }}</span><el-button :disabled="busy" @click="closeFormat">返回批量核对</el-button></div>
      <WarehouseBillFormat ref="formatEditor" :job="job" :options="options" :disabled="busy" @preview="applyFormat" />
    </section>
    <p v-if="job && !job.status" role="status">正在读取账单预览…</p>
    <template v-if="job?.status && !formatVisible">
      <div :class="{ 'c-workbench': filePolicy }">
        <nav v-if="filePolicy" class="review-queue" aria-label="核对队列"><h3>核对队列</h3><el-button v-for="(label, value) in { all: '全部', valid: '可登记', error: '待核对', existing: '已存在' }" :key="value" :type="rowStatus === (value === 'all' ? '' : value) ? 'primary' : 'default'" :disabled="busy || pendingEdit" @click="rowStatus = value === 'all' ? '' : value; query()">{{ label }}{{ value === 'all' ? '' : `（${job.counts?.[value] || 0}）` }}</el-button></nav>
      <div class="preview-main">
      <div class="workbench-toolbar"><strong>{{ job.file_name }}</strong><el-button :disabled="busy || active || pendingEdit" @click="changeFile">更换文件</el-button></div>
      <p v-if="!cnyOriginal" class="muted">此批次为历史上传，继续沿用原登记规则；重新上传同一文件不会改变历史金额或币种。</p>
      <p v-else-if="!filePolicy" class="muted">本批金额统一为 CNY。确认登记明细时自动生成结算差额费用；更正或作废已登记明细时同步重算。仅上传或编辑预览不会登记费用。</p>
      <div class="job-state" role="status"><span>{{ job.summary?.country || '国家识别中' }} · {{ job.summary?.bill_month || '月份识别中' }} · {{ states[job.status] || job.status }}</span><span v-if="active">{{ progressText }}</span><el-button link type="primary" :loading="busy" :disabled="pendingEdit" @click="refresh">刷新状态</el-button>
      <el-button v-if="!active && !hasImported && ['ready', 'failed'].includes(job.status)" link type="primary" :disabled="busy || pendingEdit" aria-label="重新匹配本地订单" @click="reparse">重新解析并匹配本地订单</el-button>
      <el-button v-if="filePolicy && !hasImported" link type="primary" :disabled="busy || active || pendingEdit" @click="formatVisible = true">配置／选择原文件格式</el-button></div>
      <el-alert v-if="job.error" :title="job.error" type="warning" :closable="false" show-icon />
      <el-alert v-if="job.summary?.settlement_summary_only" title="已读取业务结算清单，订单明细尚未重新解析；未分配金额已保留为待核对差额，不代表明细已全部核对。" type="info" :closable="false" show-icon />
      <p v-if="job.status === 'queued'" class="muted">等待后台解析，不占用页面。可关闭窗口，稍后从“最近上传”继续查看。</p>
      <template v-if="job.summary?.country && !filePolicy">
        <template v-if="job.summary.settlement && !filePolicy">
          <p><strong>业务结算清单：{{ job.summary.settlement.total }} {{ job.summary.settlement.currency || '币种待确认' }}</strong>。其他工作表仅作为明细依据，不重复叠加费用。</p>
          <p v-if="job.summary.settlement_result" role="status">已登记 {{ job.summary.settlement_result.registered_total }} {{ job.summary.settlement_result.currency }}；未落实到订单的金额保留在仓库其他处理费。</p>
          <p v-for="item in job.summary.settlement_result?.adjustments || []" :key="item.id" class="muted">{{ item.item }}：{{ item.amount }} {{ job.summary.settlement.currency }} · {{ item.warehouse_id ? archiveLabel('warehouses', item.warehouse_id) : '仓库待分配' }}</p>
          <el-button v-if="canSettle() && !active" :loading="busy" :disabled="pendingEdit || !job.summary.settlement.valid" @click="confirmSettlement">按结算清单登记／重算差额</el-button>
        </template>
        <p>{{ job.summary.country }} · {{ job.summary.bill_month }} · {{ job.summary.format }} · 订单费用 {{ job.summary.counts?.order || 0 }} 条，其他费用 {{ job.summary.counts?.other || 0 }} 条</p>
        <p class="muted">原账单金额合计（含待核对）：<span v-for="total in job.summary.totals" :key="total.currency">{{ total.amount }} {{ total.currency }}　</span></p>
        <p v-if="job.summary.corrected_totals" class="muted">修正后金额合计（含待核对）：<span v-for="total in job.summary.corrected_totals" :key="total.currency">{{ total.amount }} {{ total.currency }}　</span>保留原账单总额；确认登记后，差额自动计入仓库其他处理费。</p>
        <p class="muted">订单对账：明细 {{ job.summary.order_detail_sum }} / 账单 {{ job.summary.order_bill_total ?? '缺失' }}；差额 {{ job.summary.order_difference ?? '无法核对' }} {{ job.summary.currency }}</p>
        <p v-if="job.summary.corrected_totals" class="muted">修正后订单差额：{{ job.summary.corrected_order_difference ?? '无法核对' }} {{ job.summary.currency }}</p>
        <el-alert v-if="job.summary.correction_warning" :title="job.summary.correction_warning" type="warning" :closable="false" show-icon />
        <el-alert v-for="warning in job.summary.warnings || []" :key="warning" :title="warning" type="warning" :closable="false" />
      </template>
      <section v-if="filePolicy" aria-label="原文件结算核对" class="file-contract">
        <p>采用规则：{{ job.summary?.applied_rule?.name || '待解析' }} · {{ job.summary?.bill_month || '月份待确认' }} · 金额按原数字 CNY 登记</p>
        <div class="file-formula" aria-label="处理费差额核对"><template v-for="(label, key, index) in { file_total: '结算总额', effective_order_total: '订单明细合计', effective_other_total: '其他费用（不含差额）', processing_difference: '处理费差额' }" :key="key"><span v-if="index">{{ index === 3 ? '=' : '−' }}</span><div><small>{{ label }}</small><strong :title="`原精度：${job.summary?.[key] ?? '缺失'}`">{{ money(job.summary?.[key]) }}</strong></div></template></div>
        <p class="muted">原表处理费小计 {{ money(job.summary?.file_order_total) }} CNY，仅作核对参考。正处理费差额将在确认登记时自动计入其他处理费，名称为“处理费差额”；仅预览不登记。不按所选行或已登记金额计算，负差额保留待核对。</p>
        <el-alert v-for="item in (job.summary?.validation?.items || []).filter(i => i.level !== 'row')" :key="item.code" :title="item.message" :type="item.level === 'batch' ? 'error' : 'warning'" :closable="false" show-icon />
        <el-alert v-if="job.summary?.corrected_totals" title="预览金额已更正，处理费差额已按全部明细重算；原文件总额保留。" type="warning" :closable="false" />
        <el-collapse><el-collapse-item title="工作表覆盖与全部异常" name="coverage"><el-table :data="job.summary?.coverage || []"><el-table-column prop="sheet" label="工作表" min-width="150" /><el-table-column prop="kind" label="用途" width="110" /><el-table-column prop="count" label="提取" width="80" /><el-table-column prop="skipped" label="跳过" width="80" /><el-table-column prop="outside" label="范围外" width="90" /><el-table-column prop="reason" label="依据／说明" min-width="200" /></el-table><p>共 {{ job.summary?.validation?.count || 0 }} 项原文件异常；完整清单保留全部来源行。</p><el-button :disabled="busy" @click="downloadErrors">下载完整核对清单</el-button></el-collapse-item></el-collapse>
        <details class="file-notes"><summary>登记规则与金额说明</summary><p class="muted">处理费差额＝结算总额−全部订单明细合计−其他费用合计（不含差额本身）；预览金额调整后重算，不按勾选或已登记金额计算。金额按原数字 CNY 登记，显示两位，悬停可查看原精度。订单、预约单、包裹或完整运单唯一匹配后，店铺取自本地订单。</p></details>
      </section>
      <el-collapse v-if="!active && !hasImported && hasMappings">
        <el-collapse-item title="本账单店铺与仓库映射" name="mapping">
          <p class="muted">映射仅影响此账单，不修改档案。</p>
          <div v-for="group in (filePolicy ? ['warehouses'] : ['warehouses', 'stores'])" :key="group">
            <label v-for="item in job.summary?.unresolved?.[group] || []" :key="item.name" class="mapping-row">
              <span>{{ group === 'warehouses' ? '仓库' : '店铺' }}：{{ item.name || '原单未标明（本账单统一）' }} · {{ item.count }} 行</span>
              <el-select v-model="settings[group][item.name]" clearable filterable :disabled="pendingEdit || busy" :aria-label="`映射${group === 'warehouses' ? '仓库' : '店铺'}${item.name}`">
                <el-option v-for="target in mappingOptions(group)" :key="target.id" :value="target.id" :label="`${target.code} · ${target.name}`" />
              </el-select>
            </label>
          </div>
          <el-button :loading="busy" :disabled="pendingEdit" aria-label="应用本账单店铺与仓库映射" @click="reparse">应用映射（不导入）</el-button>
        </el-collapse-item>
      </el-collapse>
      <template v-if="['ready', 'completed', 'failed'].includes(job.status) && job.summary?.country">
        <div class="preview-controls">
          <template v-if="!filePolicy">
          <span>待导入 {{ job.counts?.valid || 0 }} · 待核对 {{ job.counts?.error || 0 }} · 已新增 {{ job.counts?.created || 0 }} · 已存在 {{ job.counts?.existing || 0 }}</span>
          <el-button v-if="job.counts?.error" :disabled="pendingEdit || busy" aria-label="查看待核对区" @click="rowStatus = 'error'; query()">待核对区（{{ job.counts.error }}）</el-button>
          <el-select v-model="rowStatus" clearable :disabled="pendingEdit || busy" placeholder="全部解析结果" aria-label="解析结果筛选" @change="query"><el-option v-for="(label, value) in rowStates" :key="value" :label="label" :value="value" /></el-select>
          </template>
          <el-select v-model="rowKind" clearable :disabled="pendingEdit || busy" placeholder="两类费用" aria-label="原账单费用类型" @change="query"><el-option label="仓库处理费" value="order" /><el-option label="其他处理费" value="other" /></el-select>
          <span v-if="filePolicy" class="muted">选择明细，在右侧核对来源或修正金额</span>
        </div>
        <p v-if="hasImported" class="muted">此账单已有导入结果，预览只读；需要修改时请到处理费草稿中处理。</p>
        <p v-else-if="!filePolicy" class="muted">仅修正本账单的待导入值，不修改原文件。展开行可查看原始值和修改记录。</p>

        <el-table v-if="filePolicy" ref="previewTable" :data="job.results || []" row-key="number" max-height="480" highlight-current-row :current-row-key="focusedRow?.number" aria-label="原账单业务明细" @selection-change="selectedRows = $event" @row-click="focusRow">
          <el-table-column type="selection" width="44" :selectable="row => !busy && !pendingEdit && ['valid', 'created', 'existing'].includes(row.status)" />
          <el-table-column label="仓库" min-width="110"><template #default="{ row }">{{ archiveLabel('warehouses', row.data.warehouse_id) }}</template></el-table-column>
          <el-table-column label="国家" width="80"><template #default="{ row }">{{ row.data.country || job.summary.country }}</template></el-table-column>
          <el-table-column :label="rowKind === 'order' ? '店铺' : rowKind === 'other' ? '费用名称' : '店铺／费用名称'" min-width="150"><template #default="{ row }">{{ row.data.kind === 'other' ? row.data.fee_item : archiveLabel('stores', row.data.store_id) }}</template></el-table-column>
          <el-table-column v-if="rowKind !== 'other'" label="订单号" min-width="180"><template #default="{ row }">{{ row.data.external_order_id || '—' }}</template></el-table-column>
          <el-table-column label="金额（CNY）" min-width="115" align="right"><template #default="{ row }"><span :title="String(row.data.amount ?? '')">{{ money(row.data.amount) }}</span></template></el-table-column>
          <el-table-column label="来源月份" width="105"><template #default="{ row }">{{ row.data.bill_month || job.summary.bill_month }}</template></el-table-column>
          <el-table-column label="状态" min-width="130"><template #default="{ row }">{{ rowStates[row.status] }}<small v-if="row.source.correction">已修正</small><small v-if="row.source.possible_duplicate">疑似重复</small></template></el-table-column>
          <el-table-column label="操作" fixed="right" width="75"><template #default="{ row }"><el-button link type="primary" :disabled="pendingEdit || busy" :aria-label="`核对第${row.number}条`" @click.stop="focusRow(row)">核对</el-button></template></el-table-column>
        </el-table>
        <el-table v-if="!filePolicy" ref="previewTable" :data="job.results || []" row-key="number" max-height="390" aria-label="原账单解析预览" @selection-change="selectedRows = $event" @row-click="focusedRow = $event">
          <el-table-column v-if="editable || filePolicy" type="selection" width="44" :selectable="row => !busy && !editRow && (filePolicy || ['valid', 'error'].includes(row.status))" />
          <el-table-column type="expand"><template #default="{ row }">
            <div class="row-details">
              <p>原始解析值（不随人工修正改变）：{{ archiveLabel('stores', original(row).store_id) }} / {{ archiveLabel('warehouses', original(row).warehouse_id) }}</p>
              <p>平台订单号：{{ original(row).external_order_id || '—' }}；金额：{{ money(original(row).amount ?? row.source.raw_amount) }} {{ original(row).currency }}；费用项目：{{ original(row).fee_item || '—' }}</p>
              <p v-if="row.source.original_order_id">原账单编号：{{ row.source.original_order_id }}；运单号：{{ row.source.tracking_numbers?.join('、') || '未提供' }}</p>
              <p v-if="row.source.settlement_evidence">原币明细：{{ row.source.settlement_evidence.original_amount }} {{ row.source.settlement_evidence.original_currency }}；结算依据：{{ row.source.settlement_evidence.settlement_amount }} {{ row.source.settlement_evidence.settlement_currency }}，不重复登记两种币种。</p>
              <p v-for="candidate in row.source.matching?.candidates || []" :key="candidate.order_id">{{ row.match_status === 'bf_candidate' ? '待确认候选' : '本地订单' }}：{{ candidate.external_order_id }} · {{ archiveLabel('stores', candidate.store_id) }}</p>
              <p>发生日期：{{ row.data.occurred_on || '仅有月份' }}；备注：{{ row.data.note || '—' }}</p>
              <el-button :disabled="busy" @click="loadAudit(row)">查看修改记录</el-button>
              <p v-if="auditRows[row.number]?.length === 0" class="muted">暂无修改记录。</p>
              <div v-for="event in auditRows[row.number] || []" :key="event.id" class="audit-entry">
                <p>{{ event.action === 'restore' ? '恢复原始值' : '编辑' }} · 操作人 #{{ event.actor }} · {{ formatTime(event.at) }} · {{ event.detail.reason || '未填写原因' }}</p>
                <p v-for="field in changedFields(event.detail.before, event.detail.after)" :key="field">{{ fieldLabels[field] || field }}：{{ displayField(field, event.detail.before[field]) }} → {{ displayField(field, event.detail.after[field]) }}</p>
              </div>
            </div>
          </template></el-table-column>
          <el-table-column label="来源" min-width="155"><template #default="{ row }"><el-button link type="primary" @click="focusedRow = row">{{ row.source.sheet }}!{{ row.source.row }}</el-button></template></el-table-column>
          <el-table-column label="类型／费用项目" min-width="170"><template #default="{ row }">{{ row.data.kind === 'order' ? '订单' : '其他' }} · <el-input v-if="editRow?.number === row.number" v-model="editForm.fee_item" aria-label="编辑费用项目" :disabled="busy" maxlength="80" /><template v-else>{{ row.data.fee_item }}</template></template></el-table-column>
          <el-table-column v-if="!filePolicy" label="原店铺／原仓库" min-width="160"><template #default="{ row }">{{ row.source.raw_store || '—' }} / {{ row.source.raw_warehouse || '未标明' }}</template></el-table-column>
          <el-table-column label="系统店铺／系统仓库" min-width="210"><template #default="{ row }">
            <template v-if="editRow?.number === row.number">
              <el-select v-if="row.data.kind === 'order' && !filePolicy" v-model="editForm.store_id" filterable clearable aria-label="编辑系统店铺" :disabled="busy"><el-option v-for="item in mappingOptions('stores')" :key="item.id" :value="item.id" :label="`${item.code} · ${item.name}`" /></el-select>
              <el-select v-model="editForm.warehouse_id" filterable aria-label="编辑系统仓库" :disabled="busy"><el-option v-for="item in mappingOptions('warehouses')" :key="item.id" :value="item.id" :label="`${item.code} · ${item.name}`" /></el-select>
            </template>
            <template v-else>{{ row.data.kind === 'other' ? '国家级费用' : archiveLabel('stores', row.data.store_id) }}<small>{{ archiveLabel('warehouses', row.data.warehouse_id) }}</small></template>
          </template></el-table-column>
          <el-table-column label="平台订单号" min-width="210"><template #default="{ row }"><el-input v-if="editRow?.number === row.number && row.data.kind === 'order'" v-model="editForm.external_order_id" aria-label="编辑平台订单号" :disabled="busy" maxlength="191" /><template v-else>{{ row.data.external_order_id || '—' }}</template></template></el-table-column>
          <el-table-column label="结算金额" min-width="190"><template #default="{ row }"><template v-if="editRow?.number === row.number">
            <el-input v-model="editForm.amount" inputmode="decimal" aria-label="编辑结算金额" :disabled="busy" />
            <el-select v-model="editForm.currency" aria-label="编辑结算币种" :disabled="busy || cnyOriginal"><el-option v-for="currency in options.currencies" :key="currency" :value="currency" :label="currency" /></el-select>
          </template><template v-else>{{ money(row.data.amount) }} {{ row.data.currency }}</template></template></el-table-column>
          <el-table-column label="解析结果／订单关联" min-width="230"><template #default="{ row }">{{ rowStates[row.status] }}<small v-if="row.source.possible_duplicate">疑似重复计费（已保留，未删除）</small><small v-if="row.source.order_unlinked">未关联本地 SaaS 订单，待核对，暂不登记</small><small>{{ matches[row.match_status] || '订单关联待核对' }}<span v-if="row.source.correction"> · 已修正</span></small><small v-if="row.error">{{ row.error }}</small></template></el-table-column>
          <el-table-column v-if="editable" label="操作" fixed="right" width="150"><template #default="{ row }">
            <template v-if="editRow?.number === row.number"><el-button link type="primary" :loading="busy" @click="saveEdit">保存并校验</el-button><el-button link :disabled="busy" @click="cancelEdit">取消</el-button></template>
            <template v-else><el-button link type="primary" :disabled="busy || pendingEdit" @click="startEdit(row)">编辑</el-button><el-button v-if="row.source.correction || row.source.correction_conflict" link :disabled="busy || pendingEdit" @click="restoreRow(row)">恢复原始值</el-button></template>
          </template></el-table-column>
        </el-table>
        <section v-if="editRow && !filePolicy" class="edit-extra" aria-label="本行编辑补充信息">
          <p>正在编辑 {{ editRow.source.sheet }}!{{ editRow.source.row }}；请保存或取消后再翻页、筛选或导入。</p>
          <p v-if="busy" role="status">正在保存并重新检查整份账单，请等待，不要重复提交。</p>
          <label>发生日期<el-date-picker v-model="editForm.occurred_on" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" aria-label="编辑发生日期" :disabled="busy" /></label>
          <label>备注<el-input v-model="editForm.note" aria-label="编辑备注" maxlength="500" :disabled="busy" /></label>
          <label>修改原因{{ reasonRequired ? '（必填）' : '（选填）' }}<el-input v-model="editReason" aria-label="本行修改原因" maxlength="500" :disabled="busy" /></label>
          <p class="muted">{{ cnyOriginal ? '金额最多六位小数，固定使用 CNY；处理费差额随预览金额更正重算。' : '金额最多六位小数；更改币种仅修正登记币种，不自动换算金额。' }}</p>
        </section>
        <section v-if="editable && selectedRows.length && !editRow" class="batch-edit" aria-label="批量修正所选记录">
          <span>已选 {{ selectedRows.length }} 条（仅当前页勾选记录）</span>
          <el-select v-model="batchField" aria-label="批量修改字段" :disabled="busy" @change="batchValue = ''"><el-option v-if="!filePolicy" label="系统店铺" value="store_id" /><el-option label="系统仓库" value="warehouse_id" /><el-option label="费用项目" value="fee_item" /></el-select>
          <el-input v-if="batchField === 'fee_item'" v-model="batchValue" aria-label="批量费用项目" maxlength="80" :disabled="busy" />
          <el-select v-else v-model="batchValue" filterable aria-label="批量目标档案" :disabled="busy"><el-option v-for="item in mappingOptions(batchField === 'store_id' ? 'stores' : 'warehouses')" :key="item.id" :value="item.id" :label="`${item.code} · ${item.name}`" /></el-select>
          <el-input v-model="batchReason" aria-label="批量修改原因" placeholder="修改原因" maxlength="500" :disabled="busy" />
          <el-button type="primary" :loading="busy" @click="saveBatch">应用并校验（不导入）</el-button><el-button :disabled="busy" @click="clearSelection">取消批量修改</el-button>
        </section>
        <div v-if="filePolicy" class="selection-summary"><span>当前页已选 {{ selectedRows.length }} 条 · {{ selectedAmount }} CNY</span><el-button :disabled="busy || pendingEdit" @click="selectPage">选择本页可登记行</el-button><el-button :disabled="busy || pendingEdit || !selectedRows.length" @click="clearSelection">清空选择</el-button></div>
        <el-pagination v-model:current-page="page" :page-size="20" :total="job.count || 0" layout="total, prev, pager, next" :disabled="busy || pendingEdit" @current-change="refresh" />
        <div v-if="!filePolicy" class="preview-controls">
          <el-button v-if="job.counts?.error" :disabled="busy" @click="downloadErrors">下载待核对清单</el-button>
          <el-checkbox v-if="job.counts?.error && job.counts?.valid" v-model="validOnly" :disabled="busy">仅导入有效记录，待核对行不导入</el-checkbox>
          <el-button v-if="job.counts?.valid" type="primary" :loading="busy" :disabled="pendingEdit || (!filePolicy && Boolean(job.summary.correction_warning)) || !canImport() || (Boolean(job.counts?.error) && !validOnly)" @click="confirmImport">确认导入有效草稿（不登记）</el-button>
        </div>
        <section v-if="filePolicy" class="file-confirmation">
          <el-button v-if="job.counts?.error" :disabled="busy" @click="downloadErrors">下载待核对清单</el-button>
          <el-checkbox v-model="coverageConfirmed" :disabled="busy || active">已核对仓库、来源月份及全部工作表覆盖</el-checkbox>
          <el-checkbox v-if="requiresDifference" v-model="differenceConfirmed" :disabled="busy || active">已核对处理费差额，确认生成一条同名其他处理费</el-checkbox>
          <el-button :disabled="!canSaveDrafts" :loading="busy" @click="saveSelectedDrafts">保存所选 {{ selectedRows.length }} 行草稿</el-button>
          <el-button type="primary" :disabled="!canConfirmFile" :loading="busy" @click="confirmFile">确认登记所选 {{ selectedRows.length }} 行</el-button>
          <p v-if="blocking">批次存在阻断项，仅可保存有效草稿，不能登记或补差。</p>
        </section>
      </template>
      <p v-if="job.status === 'completed' && !filePolicy" role="status">导入完成。费用仅保存为草稿，请回到列表核对；没有发起付款或修改订单。</p>
      </div>
      <aside v-if="filePolicy" class="row-evidence" aria-label="当前行依据">
        <h3>来源与匹配依据</h3>
        <template v-if="focusedRow">
          <p><strong>{{ focusedRow.source.sheet }} · 第 {{ focusedRow.source.row }} 行</strong></p>
          <dl><dt>原始号码</dt><dd>{{ focusedRow.source.original_order_id || original(focusedRow).external_order_id || '—' }}</dd>
          <dt>原始金额</dt><dd :title="String(focusedRow.source.raw_amount ?? original(focusedRow).amount ?? '')">{{ money(focusedRow.source.raw_amount ?? original(focusedRow).amount) }} CNY</dd>
          <dt>当前金额</dt><dd>{{ money(focusedRow.data.amount) }} CNY</dd>
          <dt>匹配结果</dt><dd>{{ matches[focusedRow.match_status] || '待核对' }}</dd></dl>
          <p v-for="candidate in focusedRow.source.matching?.candidates || []" :key="candidate.order_id">{{ candidate.external_order_id }} · {{ archiveLabel('stores', candidate.store_id) }}</p>
          <el-alert v-if="focusedRow.error" :title="focusedRow.error" type="warning" :closable="false" />
          <p v-if="focusedRow.source.possible_duplicate">疑似重复计费，已保留。</p>
          <template v-if="editRow">
            <h3>修正本行</h3>
            <label>仓库<el-select v-model="editForm.warehouse_id" filterable aria-label="编辑系统仓库" :disabled="busy"><el-option v-for="item in mappingOptions('warehouses')" :key="item.id" :value="item.id" :label="`${item.code} · ${item.name}`" /></el-select></label>
            <label v-if="editRow.data.kind === 'order'">订单号<el-input v-model="editForm.external_order_id" aria-label="编辑平台订单号" :disabled="busy" maxlength="191" /></label>
            <label v-else>费用名称<el-input v-model="editForm.fee_item" aria-label="编辑费用项目" :disabled="busy" maxlength="80" /></label>
            <label>金额（CNY）<el-input v-model="editForm.amount" inputmode="decimal" aria-label="编辑结算金额" :disabled="busy" /></label>
            <label>备注<el-input v-model="editForm.note" aria-label="编辑备注" maxlength="500" :disabled="busy" /></label>
            <label>修改原因{{ reasonRequired ? '（必填）' : '（选填）' }}<el-input v-model="editReason" aria-label="本行修改原因" maxlength="500" :disabled="busy" /></label>
            <p class="muted">金额最多六位小数；修正保留原值，并重算处理费差额。</p>
            <div class="evidence-actions"><el-button type="primary" :loading="busy" @click="saveEdit">保存并校验</el-button><el-button :disabled="busy" @click="cancelEdit">取消</el-button></div>
          </template>
          <div v-else-if="editable" class="evidence-actions"><el-button :disabled="busy || pendingEdit" @click="startEdit(focusedRow)">编辑本行</el-button><el-button v-if="focusedRow.source.correction || focusedRow.source.correction_conflict" :disabled="busy || pendingEdit" @click="restoreRow(focusedRow)">恢复原始值</el-button></div>
          <el-button :disabled="busy" @click="loadAudit(focusedRow)">查看更正历史</el-button>
          <p v-if="auditRows[focusedRow.number]?.length === 0" class="muted">暂无更正记录。</p>
          <div v-for="event in auditRows[focusedRow.number] || []" :key="event.id" class="audit-entry"><p>{{ formatTime(event.at) }} · {{ event.detail.reason }}</p><p v-for="field in changedFields(event.detail.before, event.detail.after)" :key="field">{{ fieldLabels[field] || field }}：{{ displayField(field, event.detail.before[field]) }} → {{ displayField(field, event.detail.after[field]) }}</p></div>
        </template>
        <p v-else class="muted">选择一条明细查看原始值和订单匹配依据。</p>
      </aside>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { requestApi, downloadApiFile } from '../api/request';
import { useAuthStore } from '../stores/auth';
import WarehouseBillFormat from './WarehouseBillFormat.vue';
import { warehouseMoney as money, warehouseMoneyTotal } from '../utils/warehouseMoney';

const props = defineProps({ options: { type: Object, required: true } });
const emit = defineEmits(['imported']);
const BASE = '/api/finance/warehouse-fees/original-bills/';
const auth = useAuthStore();
const states = { queued: '等待解析', parsing: '正在解析', ready: '解析完成，待核对', import_queued: '等待导入草稿', importing: '正在导入草稿', completed: '草稿导入完成', failed: '未完成，请核对' };
const progressText = computed(() => {
  const progress = job.value?.summary?.progress;
  if (job.value?.status === 'parsing') {
    if (progress?.stage === 'matching') return `正在匹配本地订单并生成预览：${job.value.processed || 0} / ${progress.total} 条`;
    return progress?.sheet ? `正在读取并核对工作表“${progress.sheet}”：已扫描 ${progress.scanned || 0} 行；完成后生成费用明细`
      : '正在读取原文件并核对全部工作表，大文件可能需要数分钟；尚未生成费用明细';
  }
  if (job.value?.status === 'queued') return '等待后台工作队列接收';
  return `已处理 ${job.value?.processed || 0} 行`;
});
const rowStates = { valid: '可导入', error: '待核对，不导入', created: '已新增草稿', existing: '已存在，跳过' };
const matches = { matched: '已匹配销售订单', unmatched: '未匹配本地订单', ambiguous: '订单匹配有歧义', not_applicable: '国家级费用，无需关联订单' };
Object.assign(matches, { booking_matched: '预约号已通过本地归档匹配订单', booking_order_missing: '预约对应关系已找到，本地销售订单待补齐', reservation_matched: '预约单已通过运单匹配本地订单', missing_order: '本地未找到订单',
  missing_tracking: '预约单缺少完整运单号', tracking_unmatched: '缺少本地物流关联',
  temu_unintegrated: 'Temu待关联', manual_pending: '疑似手工单，待核实', manual_confirmed: '手工单归属已确认',
  bf_candidate: 'BF附加后缀候选，待确认', country_conflict: '订单国家或平台冲突', store_conflict: '所选店铺与订单冲突' });
const fieldLabels = { store_id: '系统店铺', warehouse_id: '系统仓库', external_order_id: '平台订单号', fee_item: '费用项目', amount: '结算金额', currency: '结算币种', occurred_on: '发生日期', note: '备注' };
const sensitiveFields = ['store_id', 'warehouse_id', 'external_order_id', 'amount', 'currency'];
const job = ref(null), busy = ref(false), error = ref(''), history = ref([]), historyId = ref(''), page = ref(1), rowStatus = ref(''), rowKind = ref(''), validOnly = ref(false), uploadPercent = ref(null);
const feedback = ref(''), billInput = ref(null), previewTable = ref(null), editRow = ref(null), editForm = reactive({}), editReason = ref('');
const selectedRows = ref([]), batchField = ref('warehouse_id'), batchValue = ref(''), batchReason = ref(''), auditRows = reactive({});
const filePolicy = computed(() => job.value?.overrides?.registration_mode === 'file_settlement_v2');
const cnyOriginal = computed(() => filePolicy.value || job.value?.overrides?.registration_mode === 'cny_original_v1');
const formatVisible = ref(false), coverageConfirmed = ref(false), differenceConfirmed = ref(false), focusedRow = ref(null);
const openFormatAfterParse = ref(false);
const formatEditor = ref(null);
const selectedAmount = computed(() => warehouseMoneyTotal(selectedRows.value.map(row => row.data.amount)));
const blocking = computed(() => Boolean(job.value?.summary?.validation?.blocking));
const requiresDifference = computed(() => job.value?.summary?.difference_state === 'confirmation_required');
const selectedValid = computed(() => selectedRows.value.length && selectedRows.value.every(r => ['valid', 'created', 'existing'].includes(r.status)));
const canConfirmFile = computed(() => filePolicy.value && !active.value && !busy.value && !pendingEdit.value && !blocking.value && coverageConfirmed.value && (!requiresDifference.value || differenceConfirmed.value) && selectedValid.value && auth.hasPermission('finance.warehouse_fees.register'));
const canSaveDrafts = computed(() => filePolicy.value && !active.value && !busy.value && !pendingEdit.value && selectedValid.value && !job.value?.summary?.correction_warning && canImport());
const settings = reactive({ country: '', bill_month: '', currency: '', warehouses: {}, stores: {}, format_config: null, format_rule_id: null, warehouse_id: null });
const active = computed(() => ['queued', 'parsing', 'import_queued', 'importing'].includes(job.value?.status));
const hasImported = computed(() => Boolean(job.value?.counts?.created || job.value?.counts?.existing));
const hasMappings = computed(() => (filePolicy.value ? ['warehouses'] : ['warehouses', 'stores']).some(group => job.value?.summary?.unresolved?.[group]?.length));
const canImport = () => auth.hasPermission('finance.warehouse_fees.import');
const canSettle = () => canImport() && auth.hasPermission('finance.warehouse_fees.register') && auth.hasPermission('finance.warehouse_fees.edit');
const editable = computed(() => job.value?.status === 'ready' && !hasImported.value && canImport());
const editChanges = computed(() => editRow.value ? Object.fromEntries(Object.keys(fieldLabels)
  .filter(key => (editForm[key] || null) !== (editRow.value.data[key] || null)).map(key => [key, key === 'occurred_on' ? editForm[key] || null : editForm[key]])) : {});
const reasonRequired = computed(() => sensitiveFields.some(key => key in editChanges.value));
const pendingEdit = computed(() => Boolean(editRow.value || (selectedRows.value.length && (batchValue.value !== '' || batchReason.value))));
const dirty = computed(() => Boolean(formatEditor.value?.dirty || Object.keys(editChanges.value).length || editReason.value || (selectedRows.value.length && (batchValue.value !== '' || batchReason.value))));
let timer, disposed = false, requestId = 0;
const formatTime = value => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
const original = row => row.source.original_data || row.data;
const changedFields = (before, after) => Object.keys(fieldLabels).filter(field => before?.[field] !== after?.[field]);
function archiveLabel(group, id) {
  const item = props.options[group]?.find(x => x.id === id);
  return item ? `${item.code} · ${item.name}` : id ? `档案 #${id}` : '未匹配';
}
function displayField(field, value) {
  if (field === 'amount') return money(value);
  if (field === 'store_id' || field === 'warehouse_id') return archiveLabel(field === 'store_id' ? 'stores' : 'warehouses', value);
  return value ?? '—';
}
function clearSelection() {
  selectedRows.value = []; batchValue.value = ''; batchReason.value = '';
  previewTable.value?.clearSelection?.();
}
function selectPage() {
  if (busy.value || pendingEdit.value) return;
  for (const row of job.value?.results || []) if (['valid', 'created', 'existing'].includes(row.status)) previewTable.value?.toggleRowSelection(row, true);
}
function cancelEdit() { if (!busy.value) { editRow.value = null; editReason.value = ''; } }
function startEdit(row) {
  if (!editable.value || busy.value || pendingEdit.value || !['valid', 'error'].includes(row.status)) return;
  clearSelection(); focusedRow.value = row; editRow.value = JSON.parse(JSON.stringify(row)); editReason.value = ''; error.value = ''; feedback.value = '';
  for (const key of Object.keys(fieldLabels)) editForm[key] = row.data[key] ?? (['store_id', 'warehouse_id', 'occurred_on'].includes(key) ? null : '');
}
async function saveCorrections(rows, reason, operation = 'edit') {
  await run(async () => {
    const saved = await api({ method: 'post', url: BASE + job.value.id + '/', timeout: 120000,
      data: { operation, version: job.value.version, rows, reason } });
    job.value = { ...job.value, ...saved }; editRow.value = null; editReason.value = ''; clearSelection();
    for (const key of Object.keys(auditRows)) delete auditRows[key];
    validOnly.value = false; feedback.value = '修正已保存并重新校验，未导入、未登记。';
    try { await readCurrent(); } catch (e) { throw new Error(`修正已保存，但预览刷新失败：${e.message}。请刷新状态，不要重复提交。`); }
  });
}
async function saveEdit() {
  if (!editable.value || busy.value || !editRow.value) return;
  if (!Object.keys(editChanges.value).length) { cancelEdit(); return; }
  if (reasonRequired.value && !editReason.value.trim()) { error.value = '修改金额、币种或归属时，请填写修改原因。'; return; }
  await saveCorrections([{ number: editRow.value.number, changes: editChanges.value }], editReason.value.trim());
}
async function saveBatch() {
  if (!editable.value || busy.value || editRow.value || !selectedRows.value.length) return;
  if (!['store_id', 'warehouse_id', 'fee_item'].includes(batchField.value)) return;
  if (!batchValue.value || !batchReason.value.trim()) { error.value = '请选择批量目标并填写修改原因。'; return; }
  if (batchField.value === 'store_id' && selectedRows.value.some(row => row.data.kind !== 'order')) { error.value = '国家级其他费用不能设置店铺，请仅选择订单处理费。'; return; }
  try { await ElMessageBox.confirm(`仅修改明确勾选的${selectedRows.value.length}条记录的${fieldLabels[batchField.value]}，不会导入。`, '批量修正预览'); } catch { return; }
  await saveCorrections(selectedRows.value.map(row => ({ number: row.number, changes: { [batchField.value]: batchValue.value } })), batchReason.value.trim());
}
async function restoreRow(row) {
  if (!editable.value || busy.value || pendingEdit.value) return;
  let reason;
  try { reason = (await ElMessageBox.prompt('填写恢复原因；仅恢复本行原始解析值并重新校验。', '恢复原始值', { inputValidator: value => Boolean(value?.trim()) || '请填写原因' })).value; } catch { return; }
  await saveCorrections([{ number: row.number }], reason.trim(), 'restore');
}
async function loadAudit(row) {
  await run(async () => { auditRows[row.number] = (await api({ url: BASE + job.value.id + '/', params: { audit_row: row.number } })).results; });
}
async function canLeave() {
  if (busy.value) return false;
  if (formatVisible.value && formatEditor.value && !await formatEditor.value.canLeave()) return false;
  if (!formatVisible.value && dirty.value) {
    try { await ElMessageBox.confirm('本账单有未保存的修正，是否放弃修改？已保存修正不受影响。', '未保存的修改'); } catch { return false; }
  }
  cancelEdit(); clearSelection(); return true;
}
async function closeFormat() { if (!busy.value && (!formatEditor.value?.canLeave || await formatEditor.value.canLeave())) formatVisible.value = false; }
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } }
defineExpose({ canLeave });
async function api(config) {
  const result = await requestApi({ timeout: 30000, ...config, noMockFallback: true });
  if (!result.success) throw new Error(result.message || '操作失败，请重新核对。');
  return result.data;
}
async function run(task) {
  if (busy.value || !canImport()) return;
  busy.value = true; error.value = '';
  try { await task(); } catch (e) { error.value = e.message || '操作未完成，请刷新核对。'; }
  finally { busy.value = false; uploadPercent.value = null; schedule(); }
}
function schedule() {
  clearTimeout(timer);
  if (!disposed && active.value) timer = setTimeout(refresh, 2500);
}
function setSettings(value = {}) {
  Object.assign(settings, { country: value.country || '', bill_month: value.bill_month || '', currency: value.currency || '', warehouses: { ...value.warehouses }, stores: { ...value.stores }, format_config:value.format_config || null, format_rule_id:value.format_rule_id || null, warehouse_id:value.warehouse_id || null });
}
function supplied() {
  return { ...Object.fromEntries(['country', 'bill_month', 'currency', 'format_config', 'format_rule_id', 'warehouse_id'].filter(k => settings[k]).map(k => [k, settings[k]])),
    warehouses: Object.fromEntries(Object.entries(settings.warehouses).filter(([, v]) => v)), stores: Object.fromEntries(Object.entries(settings.stores).filter(([, v]) => v)) };
}
function mappingOptions(group) { return (props.options[group] || []).filter(x => !job.value?.summary?.country || x.country === job.value.summary.country); }
async function loadHistory() { history.value = (await api({ url: BASE })).results; }
async function readCurrent() {
  if (!job.value) return;
  const id = job.value.id, sequence = ++requestId;
  const result = await api({ url: BASE + id + '/', params: { page: page.value, page_size: 20, status: rowStatus.value, kind: rowKind.value } });
  if (disposed || sequence !== requestId || job.value.id !== id) return;
  const finished = result.status === 'completed' && job.value.status !== 'completed';
  job.value = result;
  focusedRow.value = result.results?.find(row => row.number === focusedRow.value?.number) || result.results?.find(row => row.status === 'error') || result.results?.[0] || null;
  if (openFormatAfterParse.value && filePolicy.value && ['ready', 'failed'].includes(result.status)) {
    formatVisible.value = true; openFormatAfterParse.value = false;
  }
  history.value = history.value.map(item => item.id === result.id ? { ...item, status: result.status } : item);
  if (finished) emit('imported');
}
async function refresh() { if (!pendingEdit.value) { clearSelection(); await run(readCurrent); } }
async function query() { if (pendingEdit.value) return; page.value = 1; await refresh(); }
async function upload(event) {
  const file = event.target.files?.[0];
  if (!file || busy.value || active.value || pendingEdit.value || !canImport()) return;
  if (!file.name.toLowerCase().endsWith('.xlsx') || file.size > 128 * 1024 * 1024) { error.value = '请选择不超过128MB的原始xlsx账单。'; return; }
  await run(async () => {
    const data = new FormData(); data.append('file', file); data.append('options', JSON.stringify({ registration_mode: 'file_settlement_v2' }));
    uploadPercent.value = 0;
    job.value = await api({ method: 'post', url: BASE, data, timeout: 300000, onUploadProgress: p => { if (p.total) uploadPercent.value = Math.round(p.loaded / p.total * 100); } });
    coverageConfirmed.value = false; differenceConfirmed.value = false; formatVisible.value = false; focusedRow.value = null;
    historyId.value = job.value.id; page.value = 1; rowStatus.value = ''; rowKind.value = ''; validOnly.value = false;
    setSettings(job.value.overrides); await readCurrent(); await loadHistory();
  });
  event.target.value = '';
}
function focusRow(row) { if (!busy.value && !pendingEdit.value) focusedRow.value = row; }
function chooseFile(configure) { openFormatAfterParse.value = configure; billInput.value?.click(); }
async function changeFile() {
  if (active.value || !await canLeave()) return;
  ++requestId; clearTimeout(timer); job.value = null; focusedRow.value = null; historyId.value = ''; error.value = ''; feedback.value = ''; openFormatAfterParse.value = false;
}
async function selectHistory(id) {
  if (pendingEdit.value) return;
  openFormatAfterParse.value = false;
  await run(async () => {
    coverageConfirmed.value = false; differenceConfirmed.value = false; formatVisible.value = false; focusedRow.value = null;
    ++requestId; job.value = { id }; page.value = 1; validOnly.value = false; rowStatus.value = ''; rowKind.value = '';
    clearSelection(); for (const key of Object.keys(auditRows)) delete auditRows[key];
    feedback.value = ''; await readCurrent(); setSettings(job.value.overrides);
  });
}
async function reparse() {
  if (!job.value || active.value || hasImported.value || pendingEdit.value) return;
  await run(async () => {
    job.value = await api({ method: 'post', url: BASE + job.value.id + '/', data: { operation: 'parse', version: job.value.version, options: supplied() } });
    page.value = 1; validOnly.value = false; rowStatus.value = ''; await readCurrent();
  });
}
async function confirmImport() {
  if (busy.value || !job.value || active.value || pendingEdit.value || (!filePolicy.value && job.value.summary?.correction_warning) || !canImport() || !job.value.counts?.valid || (job.value.counts?.error && !validOnly.value)) return;
  try { await ElMessageBox.confirm(`将${job.value.counts.valid}条有效记录导入为草稿，待核对行不导入。不会确认登记或付款。`, '确认导入费用草稿'); } catch { return; }
  await run(async () => { job.value = await api({ method: 'post', url: BASE + job.value.id + '/', data: { operation: 'import', version: job.value.version, valid_only: validOnly.value } }); await readCurrent(); });
}
async function applyFormat(options) {
  if (busy.value || active.value || hasImported.value || pendingEdit.value) return;
  await run(async () => {
    job.value = await api({ method:'post', url:BASE + job.value.id + '/', data:{ operation:'parse', version:job.value.version, options } });
    coverageConfirmed.value = false; differenceConfirmed.value = false; formatVisible.value = false; page.value = 1; await readCurrent();
  });
}
async function confirmFile() {
  if (!canConfirmFile.value) return;
  const numbers = selectedRows.value.map(r => r.number);
  try { await ElMessageBox.confirm(`仅登记所选 ${numbers.length} 行${requiresDifference.value ? '，并生成一条“处理费差额”其他处理费' : ''}。不会登记未选择行，也不会发起付款。`, '确认原文件费用'); } catch { return; }
  await run(async () => {
    job.value = { ...job.value, ...await api({ method:'post', url:BASE + job.value.id + '/', data:{ operation:'register', version:job.value.version, rows:numbers, coverage_confirmed:coverageConfirmed.value, difference_confirmed:differenceConfirmed.value } }) };
    clearSelection(); await readCurrent(); emit('imported'); feedback.value = '所选费用已登记，补差按文件唯一标识核对。';
  });
}
async function saveSelectedDrafts() {
  if (!canSaveDrafts.value) return;
  const numbers = selectedRows.value.map(row => row.number);
  try { await ElMessageBox.confirm(`仅保存所选 ${numbers.length} 行、${selectedAmount.value} CNY 为草稿，不确认登记，也不生成补差。`, '保存所选草稿'); } catch { return; }
  await run(async () => {
    job.value = { ...job.value, ...await api({ method:'post', url:BASE + job.value.id + '/', data:{ operation:'save_drafts', version:job.value.version, rows:numbers } }) };
    clearSelection(); await readCurrent(); emit('imported'); feedback.value = '所选行已保存为草稿，未登记、未生成补差。';
  });
}
async function confirmSettlement() {
  if (filePolicy.value || busy.value || active.value || pendingEdit.value || !canSettle() || !job.value?.summary?.settlement?.valid) return;
  const invoice = job.value.summary.settlement;
  try { await ElMessageBox.confirm(`按业务结算清单登记 ${invoice.total} ${invoice.currency}。已登记明细不重复计费，未分配金额和正负差额进入仓库其他处理费，无法确定仓库时保留待分配。不发起付款。`, '确认结算登记'); } catch { return; }
  await run(async () => {
    job.value = await api({ method: 'post', url: BASE + job.value.id + '/', data: { operation: 'settle', version: job.value.version } });
    await readCurrent(); emit('imported'); feedback.value = '已按结算清单核对登记，差额已同步重算。';
  });
}
async function downloadErrors() { await run(async () => { const result = await downloadApiFile(BASE + job.value.id + '/errors/', '原账单待核对清单.csv'); if (result?.success === false) throw new Error(result.message); }); }
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); run(loadHistory); });
onUnmounted(() => { disposed = true; ++requestId; clearTimeout(timer); window.removeEventListener('beforeunload', beforeUnload); });
</script>

<style scoped>
.warehouse-bill-workspace { container-type:inline-size; }
.c-workbench { display:grid; grid-template-columns:140px minmax(0,1fr) 280px; gap:16px; }
.bill-file-input { display:none; }
.file-chooser { max-width:900px; margin:32px auto; padding:32px; border:1px solid #d8e1ec; border-radius:8px; }
.file-chooser h2, .format-workspace h2 { margin:0 0 16px; font-size:20px; }
.file-chooser p { line-height:1.8; }
.history-label { display:flex; flex-direction:column; gap:8px; max-width:520px; margin-top:24px; }
.workbench-toolbar { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.c-workbench { margin-top:20px; align-items:start; }
.c-workbench .preview-main { border:1px solid #d8e1ec; border-radius:8px; padding:16px; }
.review-queue h3, .row-evidence h3 { font-size:16px; margin:0 0 8px; }
.row-evidence label { display:flex; flex-direction:column; gap:6px; margin:12px 0; }
.row-evidence dt { color:#465971; margin-top:12px; }
.row-evidence dd { margin:4px 0 0; }
.evidence-actions { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; }
.evidence-actions .el-button { margin:0; }
.preview-main, .row-evidence { min-width:0; }
.review-queue { display:flex; flex-direction:column; gap:10px; }
.review-queue .el-button { margin:0; }
.row-evidence { border:1px solid #d8e1ec; border-radius:8px; padding:12px; overflow-wrap:anywhere; max-height:calc(100vh - 160px); overflow:auto; }
.file-contract { padding:0; }
.file-contract > p { margin:8px 0; }
.file-notes { margin:8px 0; color:#465971; }
.file-notes summary { cursor:pointer; }
.file-formula { display:flex; flex-wrap:wrap; align-items:center; gap:16px; margin:16px 0; font-variant-numeric:tabular-nums; }
.file-formula strong { font-size:18px; }
.file-confirmation { display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:16px 0; }
.selection-summary { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:12px; }
.file-confirmation .el-checkbox { white-space:normal; height:auto; }
@container(max-width:1100px) { .c-workbench { grid-template-columns:120px minmax(0,1fr); } .row-evidence { grid-column:1/-1; max-height:none; } }
@container(max-width:660px) { .c-workbench { grid-template-columns:minmax(0,1fr); } .review-queue { flex-direction:row; overflow:auto; } .review-queue .el-button { flex-shrink:0; } .review-queue h3 { display:none; } .file-chooser { margin:16px 0; padding:16px; } }
@media(max-width:700px) { .file-chooser { margin:16px 0; padding:16px; } .row-evidence { max-height:none; } .review-queue h3 { display:none; } .c-workbench { grid-template-columns:minmax(0,1fr); } .review-queue { flex-direction:row; overflow:auto; } .review-queue .el-button { flex-shrink:0; } }
.muted, small { color: #465971; line-height: 1.65; }
small { display: block; }
.upload-line, .preview-controls, .job-state { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
.upload-line label { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.upload-line input { max-width: 320px; }
.upload-line > .el-select { width: 350px; }
.preview-controls > .el-select { width: 185px; }
.mapping-row { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(220px, 1fr); gap: 12px; align-items: center; margin: 12px 0; }
.row-details { padding: 12px 24px; color: #263b54; overflow-wrap: anywhere; }
.audit-entry { border-top: 1px solid #d8e1ec; margin-top: 12px; padding-top: 8px; }
.edit-extra, .batch-edit { padding: 12px; margin: 12px 0; background: #f5f8fc; border: 1px solid #d8e1ec; border-radius: 6px; }
.edit-extra label { display: inline-flex; flex-direction: column; gap: 6px; margin: 0 12px 12px 0; width: min(290px, 100%); color: #263b54; }
.edit-extra :deep(.el-date-editor) { width: 100%; }
.batch-edit { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.batch-edit > .el-select, .batch-edit > .el-input { width: 200px; }
:deep(.el-table .el-select), :deep(.el-table .el-input) { width: 100%; margin: 3px 0; }
.el-pagination { margin: 16px 0; flex-wrap: wrap; }
@media (max-width: 700px) { .mapping-row { grid-template-columns: 1fr; } .upload-line > .el-select { width: 100%; } }
</style>
