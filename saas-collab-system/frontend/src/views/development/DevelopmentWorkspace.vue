<template>
  <section class="dev-page">
    <header class="dev-header">
      <div><h1>{{ meta.title }}</h1><p>{{ meta.subtitle }}</p></div>
      <div class="dev-actions">
        <el-button @click="refresh">刷新</el-button>
        <el-button v-if="mode === 'requirements' || mode === 'review'" @click="openCompetitorPicker">关联竞品分析</el-button>
        <el-button v-if="mode === 'requirements'" type="primary" @click="requirementOpen = true">新建提报</el-button>
        <el-button v-if="mode === 'projects'" type="primary" @click="projectOpen = true">新建项目</el-button>
        <el-button v-if="mode === 'sales'" type="primary" @click="salesOpen = true">导入 CSV</el-button>
      </div>
    </header>

    <div class="metric-strip">
      <div v-for="item in metrics" :key="item.label" class="metric"><span>{{ item.label }}</span><strong>{{ item.value }}</strong><small>{{ item.note }}</small></div>
    </div>

    <div v-if="mode === 'projects'" class="stage-rail">
      <div v-for="(stage, index) in stages" :key="stage.key" class="stage" :class="{ active: index < 3 }">
        <i>{{ index + 1 }}</i><div><strong>{{ stage.label }}</strong><span>{{ stageCounts[stage.key] || 0 }} 个项目</span></div>
      </div>
    </div>

    <section class="work-panel">
      <div class="filter-row">
        <el-input v-model="search" clearable placeholder="搜索编号或商品名称" style="width:260px" />
        <el-select v-model="stageFilter" clearable placeholder="全部阶段" style="width:150px">
          <el-option v-for="stage in stages" :key="stage.key" :label="stage.label" :value="stage.key" />
        </el-select>
        <el-select v-model="siteFilter" clearable placeholder="全部站点" style="width:140px">
          <el-option v-for="site in sites" :key="site" :label="site" :value="site" />
        </el-select>
        <span class="filter-spacer" /><span class="result-count">共 {{ filteredRows.length }} 条</span>
      </div>

      <el-table :data="filteredRows" v-loading="loading" height="520" @row-click="selectRow">
        <el-table-column prop="project_no" label="项目编号" width="170" />
        <el-table-column prop="product_name" label="商品名称" min-width="220"><template #default="{ row }"><div class="product-cell"><span class="product-avatar">{{ row.product_name?.slice(0,1) }}</span><strong>{{ row.product_name }}</strong></div></template></el-table-column>
        <el-table-column prop="assigned_to_name" label="负责人" width="100" />
        <el-table-column label="目标站点" min-width="150"><template #default="{ row }"><span class="site-list">{{ (row.target_sites || []).join(' · ') }}</span></template></el-table-column>
        <el-table-column label="当前阶段" width="110"><template #default="{ row }"><el-tag effect="plain" :type="stageType(row.stage)">{{ stageLabel(row.stage) }}</el-tag></template></el-table-column>
        <el-table-column label="预计毛利率" width="110"><template #default="{ row }"><strong class="margin">{{ percent(row.estimated_margin_rate) }}</strong></template></el-table-column>
        <el-table-column prop="planned_launch_date" label="计划上架" width="120" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'completed' ? 'success' : 'primary'">{{ row.status === 'completed' ? '已完成' : '进行中' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="100"><template #default="{ row }"><el-button link type="primary" @click.stop="selectRow(row)">查看</el-button></template></el-table-column>
      </el-table>
    </section>

    <el-drawer v-model="drawerOpen" title="项目详情" size="440px">
      <template v-if="selected">
        <div class="drawer-title"><span class="product-avatar large">{{ selected.product_name?.slice(0,1) }}</span><div><h3>{{ selected.product_name }}</h3><p>{{ selected.project_no }}</p></div></div>
        <el-descriptions :column="2" border><el-descriptions-item label="当前阶段">{{ stageLabel(selected.stage) }}</el-descriptions-item><el-descriptions-item label="负责人">{{ selected.assigned_to_name }}</el-descriptions-item><el-descriptions-item label="目标站点">{{ selected.target_sites?.join(' / ') }}</el-descriptions-item><el-descriptions-item label="预计毛利">{{ percent(selected.estimated_margin_rate) }}</el-descriptions-item></el-descriptions>
        <div class="detail-block"><h4>打样评估</h4><div class="status-line"><span>样品版本 V2 · 已完成评估</span><el-tag type="success">评估通过</el-tag></div><p>尺寸、材质与包装符合预期，可进入下一阶段。</p></div>
        <div class="detail-block"><h4>多站点成本汇总</h4><div v-for="site in selected.target_sites" :key="site" class="cost-line"><span>{{ site }}</span><span>单位成本 $8.35</span><strong>{{ percent(selected.estimated_margin_rate) }}</strong></div></div>
        <div class="detail-block"><h4>上市准备度</h4><el-progress :percentage="selected.stage === 'finalized' ? 100 : 75" status="success" /></div>
        <div class="drawer-footer"><el-button>退回修改</el-button><el-button type="primary">同意进入下一阶段</el-button></div>
      </template>
    </el-drawer>

    <el-dialog v-model="requirementOpen" title="新建选品提报" width="760px">
      <el-form label-position="top">
        <el-form-item label="商品名称"><el-input v-model="requirement.product_name" /></el-form-item>
        <el-alert v-if="masterDataError" :title="masterDataError" type="warning" :closable="false" show-icon />
        <el-alert title="候选款登记只做完整性校验、分类归属和重复提醒，不设置独立强制需求审核" type="info" :closable="false" show-icon />
        <div class="form-grid">
          <el-form-item label="开发类型" required>
            <el-select v-model="requirement.development_type" filterable @change="onDevelopmentTypeChange">
              <el-option v-for="item in developmentTypes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="测款模式" required>
            <el-select v-model="requirement.trial_mode" filterable>
              <el-option v-for="item in trialModes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="商品分类（允许 L2/L3）" required>
            <el-select v-model="requirement.category_node" filterable clearable placeholder="请选择 L2 或 L3 分类">
              <el-option v-for="category in categories.filter((item) => item.is_active && [2, 3].includes(Number(item.level)))" :key="category.id" :label="`L${category.level} ${category.code} ${category.name}`" :value="category.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标站点"><el-select v-model="requirement.target_sites" multiple filterable clearable placeholder="请选择启用站点"><el-option v-for="site in sites" :key="site.id" :label="`${site.code} · ${site.name}`" :value="site.id" /></el-select></el-form-item>
          <el-form-item v-if="requirement.development_type !== 'self_design'" label="工厂原型号" required><el-input v-model="requirement.original_model" placeholder="工厂选款或微改款需填写原型号" /></el-form-item>
          <el-form-item v-if="requirement.development_type === 'self_design'" label="设计文件" required><el-input v-model="requirement.design_files" placeholder="填写设计文件或附件引用，多个值用逗号分隔" /></el-form-item>
          <el-form-item v-if="requirement.development_type === 'self_design'" label="设计稿发送日期" required><el-date-picker v-model="requirement.design_sent_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        </div>
        <p class="field-help">实际小单测款达标可直接转正；虚拟库存测款达标后先进入上新计划。</p>
        <el-collapse><el-collapse-item title="补充市场数据（选填）"><el-form-item label="参考链接"><el-input v-model="requirement.reference_link" /></el-form-item><el-form-item label="提报理由"><el-input v-model="requirement.reason" type="textarea" /></el-form-item></el-collapse-item></el-collapse>
      </el-form>

      <section class="competitor-attachment" aria-label="关联竞品分析">
        <div class="attachment-header"><div><h3>关联竞品分析</h3><p>竞品模块只读提供已完成报告；商品开发仅保存关联关系和审核快照。</p></div><el-button size="small" @click="openCompetitorPicker">选择报告</el-button></div>
        <el-alert title="评价数量不代表销量或市场规模。履约/物流问题会提示运营协同，不直接当作产品设计缺陷。" type="info" :closable="false" show-icon />
        <div v-if="selectedCompetitorReport" class="attachment-summary">
          <div class="attachment-report-line"><strong>{{ selectedCompetitorReport.product_title }}</strong><span class="report-badges"><el-tag type="success" effect="plain">实时报告 · {{ selectedCompetitorReport.status === 'completed' ? '已完成' : selectedCompetitorReport.status }}</el-tag><el-tag effect="plain">{{ formatDate(selectedCompetitorReport.data_updated_at || selectedCompetitorReport.updated_at) }}</el-tag></span></div>
          <div class="stat-mini-grid"><div><b>{{ reportStats.valid_reviews }}</b><span>有效评价</span></div><div class="positive"><b>{{ reportStats.positive }}</b><span>正面</span></div><div class="neutral"><b>{{ reportStats.neutral }}</b><span>中性</span></div><div class="negative"><b>{{ reportStats.negative }}</b><span>负面</span></div></div>
          <p class="snapshot-note">保存后将生成“审核快照”，记录本次采纳项、排除项和人工结论；快照不会随上游报告更新而改变。</p>
          <div class="selected-count">已采纳 {{ selectedInsightCount }} 项<span v-if="excludedInsightIds.length">，已排除 {{ excludedInsightIds.length }} 项</span></div>
          <el-input v-model="manualConclusion" type="textarea" :rows="2" placeholder="填写人工结论：哪些问题值得开发、哪些应交由运营/仓储处理？" />
        </div>
        <div v-if="requirementAssociations.length" class="snapshot-list"><div class="snapshot-list-title">已有审核快照</div><div v-for="association in requirementAssociations" :key="association.id" class="snapshot-row"><span>{{ association.product_title || association.report_snapshot?.product_title || association.external_report_id || association.report_id }}</span><el-tag size="small" type="success">审核快照</el-tag><el-button link type="danger" size="small" :loading="associationsLoading" @click="removeRequirementAssociation(association)">删除关联</el-button></div></div>
        <el-empty v-if="!selectedCompetitorReport" description="尚未关联竞品分析报告" :image-size="56" />
      </section>

      <template #footer><el-button @click="requirementOpen=false">取消</el-button><el-button>保存草稿</el-button><el-button type="primary" @click="submitRequirement">提交审核</el-button><el-button type="success" :loading="associationSaving" :disabled="!selectedCompetitorReport" @click="saveCompetitorAssociation">保存关联快照</el-button></template>
    </el-dialog>

    <el-dialog v-model="competitorPickerOpen" title="选择竞品分析报告" width="1060px" top="5vh">
      <div class="competitor-picker" v-loading="competitorLoading">
        <aside class="report-list">
          <div class="picker-state"><span>已完成报告</span><el-tag size="small" effect="plain">只读</el-tag></div>
          <el-empty v-if="!competitorReports.length && !competitorLoading" description="暂无可用的已完成报告" :image-size="64" />
          <button v-for="report in competitorReports" :key="report.id || report.report_id" type="button" class="report-option" :class="{ selected: competitorReportId === (report.id || report.report_id) }" @click="selectCompetitorReport(report)">
            <strong>{{ report.product_title || report.product_name || '未命名商品' }}</strong><span>{{ report.platform || '—' }} · {{ report.site || '—' }}</span><span><el-tag size="small" type="success">{{ report.status === 'completed' ? '已完成' : report.status }}</el-tag> {{ formatDate(report.data_updated_at || report.updated_at || report.completed_at) }}</span>
          </button>
          <p v-if="competitorError" class="error-text">{{ competitorError }}</p>
        </aside>
        <main v-if="selectedCompetitorReport" class="report-detail" v-loading="reportDetailLoading">
          <div class="report-detail-header"><div><h3>{{ selectedCompetitorReport.product_title }}</h3><p>{{ selectedCompetitorReport.platform }} · {{ selectedCompetitorReport.site }} · 报告ID {{ selectedCompetitorReport.report_id || selectedCompetitorReport.id }}</p></div><el-tag type="success">{{ selectedCompetitorReport.status === 'completed' ? '已完成' : selectedCompetitorReport.status }}</el-tag></div>
          <el-alert v-if="selectedCompetitorReport.is_mock" title="当前为明确标注的 Mock 报告，仅用于演示交互。" type="warning" :closable="false" show-icon />
          <div class="report-stat-grid"><div><strong>{{ reportStats.valid_reviews }}</strong><span>有效评价</span></div><div class="positive"><strong>{{ reportStats.positive }}</strong><span>正面</span></div><div class="neutral"><strong>{{ reportStats.neutral }}</strong><span>中性</span></div><div class="negative"><strong>{{ reportStats.negative }}</strong><span>负面</span></div></div>
          <p class="report-boundary">评价数量仅代表本次分析样本量，不代表销量或市场规模。</p>
          <section class="report-section"><h4>分析摘要</h4><p>{{ selectedCompetitorReport.summary || '暂无摘要' }}</p></section>
          <section class="report-section"><h4>核心洞察 <small>勾选采纳项；不采纳时请填写排除原因</small></h4>
            <div v-for="group in insightGroups" :key="group.key" class="insight-group"><h5>{{ group.label }}</h5><div v-for="item in group.items" :key="item.id" class="insight-item" :class="issueClass(item.issue_type)"><div class="insight-main"><el-checkbox :model-value="isInsightSelected(group.key, item.id)" @update:model-value="(checked) => toggleInsight(group.key, item.id, checked)">{{ item.text }}</el-checkbox><el-tag size="small" :type="issueTagType(item.issue_type)" effect="plain">{{ issueTypeLabel(item.issue_type) }}</el-tag></div><div class="exclusion-row"><el-checkbox v-model="excludedInsightIds" :label="item.id">标记排除</el-checkbox><el-input v-if="excludedInsightIds.includes(item.id)" v-model="exclusionReasons[item.id]" size="small" placeholder="填写排除原因" /></div></div></div>
          </section>
          <section class="report-section"><h4>属性分析 <small>{{ selectedCompetitorReport.attributes?.length || 0 }} 个评价维度</small></h4><el-table :data="selectedCompetitorReport.attributes || []" size="small" max-height="210"><el-table-column prop="name" label="属性" min-width="120" /><el-table-column prop="mentions" label="提及" width="58" /><el-table-column prop="positive" label="正面" width="58" /><el-table-column prop="neutral" label="中性" width="58" /><el-table-column prop="negative" label="负面" width="58" /><el-table-column label="结论" min-width="260"><template #default="{ row }"><span :class="issueClass(attributeIssueType(row))">{{ row.conclusion }}</span><el-tag size="small" :type="issueTagType(attributeIssueType(row))" effect="plain">{{ issueTypeLabel(attributeIssueType(row)) }}</el-tag></template></el-table-column></el-table></section>
          <section class="report-section"><div class="section-title-row"><h4>评价证据 <small>{{ evidenceTotal }} 条，分页加载；选择后才会写入快照</small></h4><el-button link type="primary" @click="loadEvidence">{{ evidenceLoaded ? '刷新证据' : '加载证据' }}</el-button></div><el-table v-if="evidenceLoaded" :data="evidenceRows" size="small" v-loading="evidenceLoading" max-height="180" @selection-change="handleEvidenceSelection"><el-table-column type="selection" width="42" /><el-table-column prop="attribute_name" label="属性" width="110" /><el-table-column prop="text" label="评价原文" min-width="270" /><el-table-column label="倾向" width="70"><template #default="{ row }"><el-tag size="small" :type="row.sentiment === 'negative' ? 'danger' : row.sentiment === 'positive' ? 'success' : 'info'">{{ sentimentLabel(row.sentiment) }}</el-tag></template></el-table-column></el-table><div v-if="evidenceLoaded" class="evidence-pager"><el-button size="small" :disabled="evidencePage <= 1" @click="changeEvidencePage(evidencePage - 1)">上一页</el-button><span>第 {{ evidencePage }} / {{ evidencePageCount }} 页</span><el-button size="small" :disabled="evidencePage >= evidencePageCount" @click="changeEvidencePage(evidencePage + 1)">下一页</el-button></div></section>
          <section class="report-section caution-section"><h4>注意事项</h4><ul><li v-for="caution in selectedCompetitorReport.cautions || []" :key="caution">{{ caution }}</li></ul></section>
          <el-input v-model="manualConclusion" type="textarea" :rows="3" placeholder="填写人工结论" />
        </main>
        <el-empty v-else description="选择左侧报告查看详情" :image-size="90" />
      </div>
      <template #footer><span class="picker-footer-note">选择后仍需保存关联快照，报告原文不会被导入商品开发模块。</span><el-button @click="competitorPickerOpen=false">取消</el-button><el-button type="primary" :disabled="!selectedCompetitorReport" @click="applyCompetitorReport">应用到提报</el-button></template>
    </el-dialog>
    <el-dialog v-model="projectOpen" title="新建开发项目" width="620px"><el-form label-position="top"><el-form-item label="商品名称"><el-input v-model="newProject.product_name" /></el-form-item><div class="form-grid"><el-form-item label="负责人 ID"><el-input-number v-model="newProject.assigned_to" :min="1" /></el-form-item><el-form-item label="目标站点"><el-select v-model="newProject.target_sites" multiple><el-option v-for="site in sites" :key="site" :value="site" /></el-select></el-form-item></div><el-form-item label="计划上架日期"><el-date-picker v-model="newProject.planned_launch_date" type="date" value-format="YYYY-MM-DD" /></el-form-item></el-form><template #footer><el-button @click="projectOpen=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveProject">创建项目</el-button></template></el-dialog>
    <el-dialog v-model="salesOpen" title="导入销售数据" width="620px"><el-alert title="以 SPU + 站点 + 日期作为幂等键，重复导入会更新原记录。" type="info" :closable="false" /><el-input v-model="csvText" type="textarea" :rows="9" class="csv-box" /><template #footer><el-button @click="salesOpen=false">取消</el-button><el-button type="primary" @click="importCsv">开始导入</el-button></template></el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import {
  createDevelopmentProject,
  createDevelopmentRequirement,
  createRequirementCompetitorAssociation,
  deleteRequirementCompetitorAssociation,
  fetchCompetitorReportDetail,
  fetchCompetitorReportEvidence,
  fetchCompetitorReports,
  fetchDevelopmentProjects,
  fetchRequirementCompetitorAssociations,
  importDevelopmentSales
} from '../../api/development';
import { fetchCountrySites } from '../../api/masterData';
import { fetchProductCategories } from '../../api/products';
import { collectionRows } from '../../utils/businessResponse';

const props = defineProps({ mode: { type: String, default: 'projects' } });
const mode = computed(() => props.mode);
const metas = { requirements:['选品提报','快速提报、自动去重并跟踪审核状态'], review:['需求审核','集中处理待审核需求与疑似重复项'], projects:['开发项目','从立项到定型，统一管理样品、成本和上市准备'], costs:['成本核算','按站点维护成本版本并对比预计毛利'], sales:['销售数据','幂等导入销售快照并查看单品表现'], retrospectives:['选品复盘','对照预估与实际结果沉淀开发经验'], dashboard:['效能看板','查看命中率、周期、品类和站点表现'] };
const meta = computed(() => ({ title: metas[mode.value]?.[0] || '产品开发', subtitle: metas[mode.value]?.[1] || '' }));
const rows = ref([]); const loading = ref(false); const saving = ref(false); const search = ref(''); const stageFilter = ref(''); const siteFilter = ref('');
const drawerOpen = ref(false); const selected = ref(null); const requirementOpen = ref(false); const projectOpen = ref(false); const salesOpen = ref(false);
const requirement = reactive({ id: null, research_no:'', product_name:'', category:'', category_node:null, target_sites:[], target_site_ids:[], reference_link:'', reason:'', platform:'', competitor_url:'', estimated_sales:0, estimated_gross_margin:null, risk_points:[], development_type:'factory_selection', trial_mode:'small_order', original_model:'', design_files:'', design_sent_date:'' });
const developmentTypes = [{ value: 'factory_selection', label: '工厂选款' }, { value: 'self_design', label: '自有设计（轻量）' }, { value: 'micro_revision', label: '微改款（预留）' }];
const trialModes = [{ value: 'small_order', label: '实际小单测款' }, { value: 'virtual', label: '虚拟库存测款' }];
const newProject = reactive({ product_name:'', assigned_to:1, target_sites:[], planned_launch_date:'', development_source:'internal', project_no:`DEV-${Date.now()}` });
const csvText = ref('spu_code,site,platform,snapshot_date,daily_sales_qty,daily_sales_amount_usd,ad_spend\n');
const sites = ref([]); const categories = ref([]); const masterDataError = ref('');
const stages = [{key:'initiated',label:'立项'},{key:'design',label:'设计'},{key:'sampling',label:'打样'},{key:'review',label:'评审'},{key:'finalized',label:'定型'}];
const competitorPickerOpen = ref(false); const competitorLoading = ref(false); const reportDetailLoading = ref(false); const competitorError = ref('');
const competitorReports = ref([]); const competitorReportId = ref(''); const selectedCompetitorReport = ref(null); const associationSaving = ref(false); const manualConclusion = ref('');
const requirementAssociations = ref([]); const associationsLoading = ref(false);
const selectedStrengthIds = ref([]); const selectedPainPointIds = ref([]); const selectedRecommendationIds = ref([]); const excludedInsightIds = ref([]); const exclusionReasons = reactive({});
const evidenceRows = ref([]); const selectedEvidenceIds = ref([]); const evidencePage = ref(1); const evidencePageSize = ref(5); const evidenceTotal = ref(0); const evidenceLoaded = ref(false); const evidenceLoading = ref(false);
const stageCounts = computed(() => Object.fromEntries(stages.map(s => [s.key, rows.value.filter(r => r.stage === s.key).length])));
const filteredRows = computed(() => rows.value.filter(r => (!search.value || `${r.project_no}${r.product_name}`.toLowerCase().includes(search.value.toLowerCase())) && (!stageFilter.value || r.stage === stageFilter.value) && (!siteFilter.value || r.target_sites?.includes(siteFilter.value))));
const metrics = computed(() => [{label:'开发项目总数',value:rows.value.length,note:'全链路项目'},{label:'本月立项',value:rows.value.filter(r=>r.stage==='initiated').length,note:'等待设计'},{label:'平均开发周期',value:'42 天',note:'较上月 -5.6%'},{label:'平均毛利率',value:'34.1%',note:'目标 32%'},{label:'定型待发布',value:rows.value.filter(r=>r.stage==='finalized').length,note:'需完成刊登'}]);
const reportStats = computed(() => {
  const stats = selectedCompetitorReport.value?.statistics || selectedCompetitorReport.value?.stats || {};
  return { valid_reviews: stats.valid_reviews ?? stats.valid ?? 0, positive: stats.positive ?? 0, neutral: stats.neutral ?? 0, negative: stats.negative ?? 0 };
});
const evidencePageCount = computed(() => Math.max(Math.ceil(evidenceTotal.value / evidencePageSize.value), 1));
const selectedInsightCount = computed(() => selectedStrengthIds.value.length + selectedPainPointIds.value.length + selectedRecommendationIds.value.length);
const insightGroups = computed(() => {
  const insights = selectedCompetitorReport.value?.insights || {};
  const normalize = (items, key) => (items || []).map((item, index) => {
    const text = typeof item === 'string' ? item : (item.text || item.conclusion || item.label || '');
    const inferredType = item?.issue_type || (/(履约|错发|漏发|出库|仓储)/.test(text) ? 'fulfillment' : /(物流|客服|配送|未收到)/.test(text) ? 'logistics' : key === 'recommendations' && /面料|质检|供应|批次/.test(text) ? 'supply_chain' : 'product');
    return { ...(typeof item === 'object' ? item : {}), id: item?.id || item?.code || `${key}-${index}`, text, issue_type: inferredType };
  });
  return [
    { key: 'strengths', label: '主要优点', items: normalize(insights.strengths || insights.strengths_items, 'strengths') },
    { key: 'pain_points', label: '主要痛点', items: normalize(insights.pain_points || insights.painPoints, 'pain_points') },
    { key: 'recommendations', label: '改进建议', items: normalize(insights.recommendations || insights.improvement_suggestions, 'recommendations') }
  ];
});
function stageLabel(value){ return stages.find(s=>s.key===value)?.label || value; } function stageType(v){ return v==='finalized'?'success':v==='review'?'warning':'primary'; } function percent(v){ return v == null ? '—' : `${(Number(v)*100).toFixed(1)}%`; }
function selectRow(row){ selected.value=row; drawerOpen.value=true; }
async function refresh(){ loading.value=true; masterDataError.value=''; const [res, categoryRes, siteRes] = await Promise.all([fetchDevelopmentProjects(), fetchProductCategories(), fetchCountrySites({ status: 'active', page_size: 100 })]); rows.value=Array.isArray(res.data)?res.data:(res.data?.results||[]); categories.value=collectionRows(categoryRes?.data); sites.value=collectionRows(siteRes?.data).filter((item) => item.status === 'active'); if (!categoryRes?.success || !siteRes?.success) masterDataError.value='基础数据加载失败，请刷新后重试'; loading.value=false; }
async function saveProject(){ saving.value=true; const res=await createDevelopmentProject(newProject); saving.value=false; if(res.success){ ElMessage.success('项目已创建'); projectOpen.value=false; refresh(); } else ElMessage.error(res.message); }
async function importCsv(){ const res=await importDevelopmentSales(csvText.value); if(res.success){ ElMessage.success(`导入完成：${res.data.total} 条`); salesOpen.value=false; } }
function formatDate(value){ if(!value) return '更新时间未知'; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false }); }
function attributeIssueType(attribute){ const value = attribute?.issue_type; if (value) return value; const code = `${attribute?.code || ''} ${attribute?.name || ''}`; return /(履约|错发|漏发|出库|仓储|fulfillment)/i.test(code) ? 'fulfillment' : /(物流|客服|配送|logistics|service)/i.test(code) ? 'logistics' : 'product'; }
function issueTypeLabel(value){ return value === 'fulfillment' ? '履约/仓储' : value === 'logistics' ? '物流/客服' : value === 'supply_chain' ? '供应链' : '产品'; }
function issueTagType(value){ return value === 'fulfillment' || value === 'logistics' ? 'warning' : value === 'supply_chain' ? 'info' : 'success'; }
function issueClass(value){ return `issue-${value || 'product'}`; }
function sentimentLabel(value){ return value === 'negative' ? '负面' : value === 'positive' ? '正面' : '中性'; }
function selectionFor(key){ return key === 'strengths' ? selectedStrengthIds : key === 'pain_points' ? selectedPainPointIds : selectedRecommendationIds; }
function isInsightSelected(key, id){ return selectionFor(key).value.includes(id); }
function toggleInsight(key, id, checked){ const selection = selectionFor(key); selection.value = checked ? [...new Set([...selection.value, id])] : selection.value.filter((item) => item !== id); }
function resetCompetitorSelection(){ selectedStrengthIds.value = []; selectedPainPointIds.value = []; selectedRecommendationIds.value = []; excludedInsightIds.value = []; Object.keys(exclusionReasons).forEach((key) => delete exclusionReasons[key]); manualConclusion.value = ''; evidenceRows.value = []; selectedEvidenceIds.value = []; evidencePage.value = 1; evidenceTotal.value = 0; evidenceLoaded.value = false; }
function reportIdentifier(report){ return report?.id || report?.report_id; }
async function openCompetitorPicker(){ competitorPickerOpen.value = true; competitorError.value = ''; if (requirement.id) await loadRequirementAssociations(); if (!competitorReports.value.length) await loadCompetitorReports(); }
async function loadCompetitorReports(){ competitorLoading.value = true; competitorError.value = ''; const response = await fetchCompetitorReports(); competitorLoading.value = false; if (!response?.success) { competitorError.value = response?.message || '竞品报告暂不可用，请稍后重试。'; return; } const data = response.data || {}; const reports = Array.isArray(data) ? data : (data.items || data.results || []); competitorReports.value = reports.filter((report) => String(report.status || '').toLowerCase() === 'completed'); if (!selectedCompetitorReport.value && competitorReports.value.length) await selectCompetitorReport(competitorReports.value[0]); }
async function selectCompetitorReport(report){ const id = reportIdentifier(report); if (!id) return; competitorReportId.value = id; reportDetailLoading.value = true; const response = await fetchCompetitorReportDetail(id); reportDetailLoading.value = false; if (!response?.success) { competitorError.value = response?.message || '竞品报告详情暂不可用。'; return; } const detail = response.data || report; selectedCompetitorReport.value = detail.report || detail; resetCompetitorSelection(); }
async function loadRequirementAssociations(){ if (!requirement.id) return; associationsLoading.value = true; const response = await fetchRequirementCompetitorAssociations(requirement.id); associationsLoading.value = false; if (!response?.success) return; const data = response.data || {}; requirementAssociations.value = Array.isArray(data) ? data : (data.items || data.results || []); }
async function removeRequirementAssociation(association){ if (!requirement.id || !association?.id) return; associationsLoading.value = true; const response = await deleteRequirementCompetitorAssociation(requirement.id, association.id); associationsLoading.value = false; if (response?.success) { requirementAssociations.value = requirementAssociations.value.filter((item) => item.id !== association.id); ElMessage.success('关联已删除'); } else ElMessage.error(response?.message || '关联删除失败。'); }
function applyCompetitorReport(){ if (!selectedCompetitorReport.value) return; competitorPickerOpen.value = false; if (!requirementOpen.value) requirementOpen.value = true; }
function onDevelopmentTypeChange(value){ if (value === 'self_design' && !requirement.original_model) requirement.original_model = '无（自有设计）'; if (value !== 'self_design' && requirement.original_model === '无（自有设计）') requirement.original_model = ''; }
async function loadEvidence(){ if (!selectedCompetitorReport.value) return; evidenceLoading.value = true; const response = await fetchCompetitorReportEvidence(reportIdentifier(selectedCompetitorReport.value), { page: evidencePage.value, page_size: evidencePageSize.value }); evidenceLoading.value = false; if (!response?.success) { ElMessage.warning(response?.message || '评价证据暂不可用。'); return; } const data = response.data || {}; const raw = Array.isArray(data) ? data : (data.items || data.results || []); evidenceRows.value = raw.map((item) => ({ ...item, id: item.id || item.evidence_id, text: item.text || item.review || item.original_text || '', attribute_name: item.attribute_name || item.attribute_code || '未分类' })); evidenceTotal.value = Number(data.total ?? data.count ?? evidenceRows.value.length); evidenceLoaded.value = true; }
async function changeEvidencePage(page){ evidencePage.value = page; await loadEvidence(); }
function handleEvidenceSelection(selection){ const currentIds = new Set(selection.map((item) => item.id).filter(Boolean)); const pageIds = new Set(evidenceRows.value.map((item) => item.id).filter(Boolean)); selectedEvidenceIds.value = [...new Set([...selectedEvidenceIds.value.filter((id) => !pageIds.has(id)), ...currentIds])]; }
function buildAssociationPayload(){
  const exclusions = excludedInsightIds.value.map((id) => ({ id, reason: exclusionReasons[id] || '' }));
  const selectedTexts = (groupKey, ids) => insightGroups.value.find((group) => group.key === groupKey)?.items.filter((item) => ids.includes(item.id)).map((item) => item.text) || [];
  return {
    report_id: reportIdentifier(selectedCompetitorReport.value),
    is_primary: true,
    relation_type: 'primary',
    reason: manualConclusion.value,
    selected_strengths: selectedTexts('strengths', selectedStrengthIds.value),
    selected_pain_points: selectedTexts('pain_points', selectedPainPointIds.value),
    selected_recommendations: selectedTexts('recommendations', selectedRecommendationIds.value),
    evidence_ids: selectedEvidenceIds.value,
    operator_conclusion: manualConclusion.value,
    excluded_items: exclusions
  };
}
function generatedResearchNo(){ const date = new Date().toISOString().slice(0, 10).replaceAll('-', ''); return `REQ-${date}-${String(Math.floor(Math.random() * 900) + 100)}`; }
async function persistCompetitorAssociation(requirementId){
  if (!selectedCompetitorReport.value || !requirementId) return false;
  const missingReasons = excludedInsightIds.value.filter((id) => !String(exclusionReasons[id] || '').trim());
  if (missingReasons.length) { ElMessage.warning('请为每个排除项填写排除原因。'); return false; }
  associationSaving.value = true;
  const response = await createRequirementCompetitorAssociation(requirementId, buildAssociationPayload());
  associationSaving.value = false;
  if (!response?.success) { ElMessage.error(response?.message || '竞品关联保存失败。'); return false; }
  requirement.id = requirementId;
  await loadRequirementAssociations();
  return true;
}
async function saveCompetitorAssociation(){
  if (!selectedCompetitorReport.value) return;
  const missingReasons = excludedInsightIds.value.filter((id) => !String(exclusionReasons[id] || '').trim());
  if (missingReasons.length) { ElMessage.warning('请为每个排除项填写排除原因。'); return; }
  let requirementId = requirement.id;
  if (!requirementId && mode.value === 'requirements') {
    const created = await saveRequirement();
    requirementId = created?.id;
  }
  if (!requirementId) { ElMessage.warning('请先保存选品需求，取得需求编号后再保存关联快照。'); return; }
  if (await persistCompetitorAssociation(requirementId)) ElMessage.success('竞品关联已保存为审核快照');
}
async function saveRequirement(){
  const researchNo = requirement.research_no || generatedResearchNo();
  const designFiles = Array.isArray(requirement.design_files) ? requirement.design_files : String(requirement.design_files || '').split(',').map((item) => item.trim()).filter(Boolean);
  const payload = { research_no: researchNo, product_name: requirement.product_name, platform: requirement.platform || 'multi-site', category_node: requirement.category_node || null, target_site_ids: [...(requirement.target_sites || [])], competitor_url: requirement.competitor_url || '', estimated_sales: Number(requirement.estimated_sales || 0), estimated_gross_margin: requirement.estimated_gross_margin, risk_points: [...(requirement.risk_points || []), ...(requirement.reason ? [requirement.reason] : [])], development_type: requirement.development_type, trial_mode: requirement.trial_mode, original_model: requirement.development_type === 'self_design' ? '无（自有设计）' : String(requirement.original_model || '').trim(), design_files: requirement.development_type === 'self_design' ? designFiles : [], design_sent_date: requirement.development_type === 'self_design' ? requirement.design_sent_date || null : null };
  const response = await createDevelopmentRequirement(payload);
  if (!response?.success) { ElMessage.error(response?.message || '选品需求保存失败。'); return null; }
  const item = response.data || {};
  requirement.id = item.id || item.requirement_id;
  requirement.research_no = item.research_no || researchNo;
  return item;
}
async function submitRequirement(){ const item = await saveRequirement(); if (!item) return; if (selectedCompetitorReport.value && !(await persistCompetitorAssociation(item.id))) return; requirementOpen.value = false; ElMessage.success(selectedCompetitorReport.value ? '选品需求与竞品审核快照已提交' : '选品需求已提交'); }
onMounted(refresh);
</script>

<style scoped>
.dev-page{min-width:980px;color:#172033}.dev-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px}.dev-header h1{margin:0;font-size:26px}.dev-header p{margin:7px 0 0;color:#64748b}.dev-actions{display:flex;gap:10px}.metric-strip{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid #dbe3ee;border-radius:8px;background:#fff;margin-bottom:16px}.metric{padding:18px 20px;border-right:1px solid #e6ebf2}.metric:last-child{border-right:0}.metric span,.metric small{display:block;color:#718096;font-size:12px}.metric strong{display:block;margin:7px 0 5px;font-size:25px;color:#172033}.stage-rail{display:grid;grid-template-columns:repeat(5,1fr);padding:18px 22px;border:1px solid #dbe3ee;border-radius:8px;background:#fff;margin-bottom:16px}.stage{position:relative;display:flex;align-items:center;gap:10px}.stage:not(:last-child):after{content:'';position:absolute;right:18px;width:42%;height:1px;background:#dbe3ee}.stage i{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#edf1f6;color:#64748b;font-style:normal;font-weight:700}.stage.active i{background:#2563eb;color:white}.stage div{display:flex;flex-direction:column}.stage strong{font-size:14px}.stage span{margin-top:4px;color:#718096;font-size:11px}.work-panel{border:1px solid #dbe3ee;border-radius:8px;background:#fff;overflow:hidden}.filter-row{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid #e6ebf2}.filter-spacer{flex:1}.result-count{color:#718096;font-size:12px}.product-cell{display:flex;align-items:center;gap:10px}.product-avatar{display:grid;place-items:center;width:34px;height:34px;border:1px solid #dbe3ee;border-radius:7px;background:#f5f8fc;color:#2563eb}.product-avatar.large{width:52px;height:52px;font-size:20px}.site-list{font-size:12px;color:#475569}.margin{color:#16a36a}.drawer-title{display:flex;gap:12px;align-items:center;margin-bottom:20px}.drawer-title h3,.drawer-title p{margin:0}.drawer-title p{margin-top:5px;color:#718096}.detail-block{padding:16px 0;border-bottom:1px solid #e6ebf2}.detail-block h4{margin:0 0 12px}.detail-block p{color:#64748b;font-size:13px;line-height:1.6}.status-line,.cost-line{display:flex;justify-content:space-between;gap:12px;align-items:center}.cost-line{padding:9px 0;font-size:13px}.cost-line strong{color:#16a36a}.drawer-footer{position:absolute;right:20px;bottom:20px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.csv-box{margin-top:16px;font-family:monospace}
.competitor-attachment{margin-top:18px;border:1px solid #dbe3ee;border-radius:8px;padding:16px;background:#fbfdff}.attachment-header,.attachment-report-line,.section-title-row,.report-detail-header,.picker-state,.snapshot-row{display:flex;align-items:center;justify-content:space-between;gap:12px}.attachment-header h3{margin:0;font-size:16px}.attachment-header p{margin:5px 0 12px;color:#64748b;font-size:12px}.attachment-summary{margin-top:14px}.report-badges{display:flex;gap:7px;align-items:center}.stat-mini-grid,.report-stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}.stat-mini-grid>div,.report-stat-grid>div{padding:9px;border:1px solid #e5eaf1;border-radius:6px;background:#fff;text-align:center}.stat-mini-grid b,.report-stat-grid strong{display:block;font-size:19px}.stat-mini-grid span,.report-stat-grid span{display:block;margin-top:3px;color:#718096;font-size:11px}.positive b,.positive strong{color:#168755}.neutral b,.neutral strong{color:#8a6c00}.negative b,.negative strong{color:#d03939}.snapshot-note,.report-boundary{margin:8px 0;color:#64748b;font-size:12px;line-height:1.6}.selected-count{margin:9px 0;color:#2563eb;font-size:12px}.snapshot-list{margin-top:14px;padding-top:12px;border-top:1px solid #e5eaf1}.snapshot-list-title{margin-bottom:8px;font-size:12px;font-weight:600;color:#475569}.snapshot-row{padding:7px 0;font-size:12px}.competitor-picker{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:620px;border:1px solid #e5eaf1;border-radius:8px;overflow:hidden}.report-list{padding:12px;border-right:1px solid #e5eaf1;background:#f8fafc;overflow:auto}.report-option{display:flex;flex-direction:column;gap:5px;width:100%;margin-top:8px;padding:12px;border:1px solid #dbe3ee;border-radius:7px;background:#fff;text-align:left;cursor:pointer}.report-option:hover,.report-option.selected{border-color:#2563eb;box-shadow:0 0 0 1px #2563eb}.report-option span{font-size:11px;color:#64748b}.report-detail{padding:18px;overflow:auto}.report-detail-header h3{margin:0;font-size:18px}.report-detail-header p{margin:5px 0 15px;color:#64748b;font-size:12px}.report-boundary{padding:8px 10px;border-radius:5px;background:#fff7e6;color:#805a00}.report-section{padding:13px 0;border-top:1px solid #e5eaf1}.report-section h4{margin:0 0 9px;font-size:14px}.report-section h4 small{font-weight:400;color:#94a3b8}.report-section p{margin:0;color:#475569;font-size:13px;line-height:1.7}.insight-group h5{margin:10px 0 6px;font-size:12px;color:#475569}.insight-item{margin:5px 0;padding:8px;border:1px solid #e5eaf1;border-left:3px solid #16a36a;border-radius:5px;background:#fff}.insight-item.issue-fulfillment,.insight-item.issue-logistics{border-left-color:#d97706;background:#fffbeb}.insight-item.issue-supply_chain{border-left-color:#64748b}.insight-main{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.insight-main .el-checkbox{flex:1}.exclusion-row{display:flex;align-items:center;gap:8px;margin-top:4px;padding-left:24px}.exclusion-row .el-input{max-width:270px}.issue-fulfillment,.issue-logistics{color:#895b00}.issue-supply_chain{color:#475569}.report-section .el-tag{margin-left:7px}.report-section ul{margin:0;padding-left:18px;color:#64748b;font-size:12px;line-height:1.8}.evidence-pager{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:8px;color:#64748b;font-size:12px}.picker-footer-note{margin-right:auto;color:#64748b;font-size:12px}.error-text{margin:12px 0;color:#d03939;font-size:12px}
@media(max-width:1100px){.metric-strip{grid-template-columns:repeat(3,1fr)}.metric:nth-child(3){border-right:0}.stage-rail{padding:14px}.stage:not(:last-child):after{display:none}}@media(max-width:900px){.dev-page{min-width:0}.dev-header{gap:12px}.metric-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.metric{padding:14px}.stage-rail{display:flex;gap:24px;overflow-x:auto}.stage{min-width:112px}.filter-row{flex-wrap:wrap}.filter-spacer{display:none}.form-grid{grid-template-columns:1fr}.work-panel{overflow-x:auto}.competitor-picker{grid-template-columns:1fr}.report-list{max-height:220px;border-right:0;border-bottom:1px solid #e5eaf1}.report-detail{max-height:none}.attachment-report-line{align-items:flex-start;flex-direction:column}}
</style>
