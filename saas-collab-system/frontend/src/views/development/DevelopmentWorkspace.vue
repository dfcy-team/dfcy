<template>
  <section class="dev-page">
    <header class="dev-header">
      <div>
        <h1>{{ meta.title }}</h1>
        <p>{{ meta.subtitle }}</p>
      </div>
      <div class="dev-actions">
        <el-button @click="refresh">刷新</el-button>
        <el-button v-if="canonicalMode === 'candidates'" type="primary" @click="openCandidateForm">
          新建候选款
        </el-button>
      </div>
    </header>

    <el-alert v-if="meta.notice" :title="meta.notice" type="info" :closable="false" show-icon class="dev-notice" />

    <div class="metric-strip">
      <div v-for="metric in metrics" :key="metric.label" class="metric">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small>{{ metric.note }}</small>
      </div>
    </div>

    <section class="work-panel">
      <div class="filter-row">
        <el-input v-model="search" clearable placeholder="搜索编号、商品名称或供应商" @keyup.enter="refresh" />
        <el-select v-model="statusFilter" clearable placeholder="全部状态" @change="refresh">
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <span class="filter-spacer" />
        <span class="result-count">共 {{ filteredRows.length }} 条</span>
      </div>

      <el-table :data="filteredRows" v-loading="loading" row-key="id" class="dev-table" @row-click="selectRow">
        <el-table-column v-for="column in activeConfig.columns" :key="column.key" :label="column.label" :prop="column.key" :min-width="column.minWidth || 130">
          <template #default="{ row }">
            <el-tag v-if="column.key === 'status' || column.key === 'trial_status'" :type="statusType(valueFor(row, column.key))" effect="plain">
              {{ formatStatus(valueFor(row, column.key)) }}
            </el-tag>
            <span v-else>{{ formatCell(valueFor(row, column.key)) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" fixed="right" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="selectRow(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filteredRows.length" :description="emptyDescription" />
    </section>

    <el-drawer v-model="drawerOpen" :title="`${meta.title}详情`" size="480px">
      <template v-if="selected">
        <div class="drawer-title">
          <span class="record-avatar">{{ String(valueFor(selected, 'product_name') || valueFor(selected, 'name') || '?').slice(0, 1) }}</span>
          <div>
            <h3>{{ valueFor(selected, 'product_name') || valueFor(selected, 'name') || '未命名记录' }}</h3>
            <p>{{ valueFor(selected, 'candidate_no') || valueFor(selected, 'project_no') || `#${selected.id || '—'}` }}</p>
          </div>
        </div>
        <el-descriptions :column="1" border>
          <el-descriptions-item v-for="item in detailRows" :key="item.key" :label="item.label">
            <el-tag v-if="item.key === 'status' || item.key === 'trial_status'" :type="statusType(item.value)">{{ formatStatus(item.value) }}</el-tag>
            <span v-else>{{ formatCell(item.value) }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <el-empty v-else description="暂无详情" />
    </el-drawer>

    <el-dialog v-model="candidateOpen" title="新建候选款" width="680px" destroy-on-close>
      <el-alert title="前期仅做完整性校验和分类归属，不设置独立强制需求审核；保存后可继续样品、比价和成本流程。" type="info" :closable="false" show-icon class="form-notice" />
      <el-form ref="candidateFormRef" :model="candidate" :rules="candidateRules" label-position="top">
        <div class="form-grid">
          <el-form-item label="商品名称" prop="product_name" required>
            <el-input v-model="candidate.product_name" placeholder="请输入候选商品名称" />
          </el-form-item>
          <el-form-item label="开发类型" prop="development_type" required>
            <el-select v-model="candidate.development_type" style="width: 100%" @change="onDevelopmentTypeChange">
              <el-option v-for="item in developmentTypes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="测款模式" prop="trial_mode" required>
            <el-select v-model="candidate.trial_mode" style="width: 100%">
              <el-option v-for="item in trialModes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="商品分类（允许 L2/L3）" prop="category_node" required>
            <el-select v-model="candidate.category_node" filterable clearable style="width: 100%" placeholder="请选择 L2 或 L3 分类">
              <el-option v-for="item in categoryOptions" :key="item.id" :label="item.path" :value="Number(item.id)" />
            </el-select>
            <small class="field-help">可先归属 L2，后续开发中再细化到 L3；不会增加前期审核。</small>
          </el-form-item>
          <el-form-item v-if="candidate.development_type !== 'self_design'" label="工厂原型号" prop="original_model" required>
            <el-input v-model="candidate.original_model" placeholder="工厂选款/微改款时必填" />
          </el-form-item>
          <el-form-item v-else label="工厂原型号">
            <el-input v-model="candidate.original_model" disabled placeholder="无（自有设计）" />
          </el-form-item>
          <el-form-item v-if="candidate.development_type === 'self_design'" label="设计附件" prop="design_files" required>
            <el-input v-model="candidate.design_file_reference" placeholder="附件地址或文件标识，多个用逗号分隔" />
          </el-form-item>
          <el-form-item v-if="candidate.development_type === 'self_design'" label="设计稿发送日期" prop="design_sent_date" required>
            <el-date-picker v-model="candidate.design_sent_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="来源工厂">
            <el-select v-model="candidate.supplier" filterable clearable style="width: 100%" placeholder="可在样品/比价阶段补充">
              <el-option v-for="item in supplierOptions" :key="item.id" :label="`${item.name || item.code} · ${item.code || ''}`" :value="Number(item.id)" />
            </el-select>
          </el-form-item>
          <el-form-item label="计划上架日期">
            <el-date-picker v-model="candidate.planned_launch_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
        </div>
        <el-form-item label="选款理由/设计说明">
          <el-input v-model="candidate.development_reason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="candidateOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCandidate">保存候选款</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import {
  createDevelopmentCandidate,
  fetchDevelopmentCandidate,
  fetchDevelopmentCandidates,
  fetchDevelopmentCompetitors,
  fetchDevelopmentElimination,
  fetchDevelopmentEliminations,
  fetchDevelopmentListingDecision,
  fetchDevelopmentListingDecisions,
  fetchDevelopmentQuotation,
  fetchDevelopmentQuotations,
  fetchDevelopmentReorderDecision,
  fetchDevelopmentReorderDecisions,
  fetchDevelopmentSample,
  fetchDevelopmentSamples,
  fetchDevelopmentSettings,
  fetchDevelopmentSetting,
  fetchDevelopmentTrial,
  fetchDevelopmentTrials,
  fetchDevelopmentProjects
} from '../../api/development';
import { fetchProductCategories } from '../../api/products';
import { fetchSupplierMasters } from '../../api/masterData';
import { collectionRows } from '../../utils/businessResponse';

const props = defineProps({ mode: { type: String, default: 'candidates' } });

const modeAliases = { requirements: 'candidates', review: 'candidates', projects: 'candidates', sales: 'trials', retrospectives: 'eliminations', dashboard: 'candidates' };
const modeConfigs = {
  candidates: {
    title: '候选款登记',
    subtitle: '统一登记工厂选款和自有设计，后续并行进入样品、比价与成本流程。',
    notice: '候选款只做完整性校验、分类归属和重复提醒，不设置独立强制需求审核。',
    fetch: fetchDevelopmentCandidates,
    detail: fetchDevelopmentCandidate,
    columns: [
      { key: 'candidate_no', label: '开发编码', minWidth: 170 }, { key: 'product_name', label: '商品名称', minWidth: 190 },
      { key: 'development_type', label: '开发类型' }, { key: 'trial_mode', label: '测款模式' },
      { key: 'category_path', label: '商品分类', minWidth: 220 }, { key: 'status', label: '状态' }, { key: 'created_at', label: '登记时间', minWidth: 150 }
    ]
  },
  competitors: {
    title: '竞品监控', subtitle: '维护竞品关联、价格和销量快照，为候选款决策提供可追溯依据。', notice: '外部竞品采集服务尚未接入；当前接口边界已保留，不会用候选款数据冒充竞品观测。',
    fetch: fetchDevelopmentCompetitors,
    columns: [
      { key: 'competitor_name', label: '竞品名称', minWidth: 190 }, { key: 'platform', label: '平台' }, { key: 'country', label: '国家站点' },
      { key: 'price', label: '价格' }, { key: 'sales', label: '销量' }, { key: 'status', label: '监控状态' }, { key: 'updated_at', label: '最近更新', minWidth: 150 }
    ]
  },
  samples: {
    title: '样品/打样管理', subtitle: '统一收样评级与设计打样确认，支持多轮样品记录和逆向改样。', fetch: fetchDevelopmentSamples, detail: fetchDevelopmentSample,
    columns: [
      { key: 'sample_no', label: '样品编号', minWidth: 170 }, { key: 'project_no', label: '开发编码', minWidth: 170 }, { key: 'supplier_name', label: '供应商', minWidth: 150 },
      { key: 'round', label: '打样轮次' }, { key: 'evaluation_result', label: '确认结论' }, { key: 'status', label: '状态' }, { key: 'received_at', label: '收样日期', minWidth: 140 }
    ]
  },
  quotations: {
    title: '比价管理', subtitle: '一个候选款可挂多家报价，并明确主供与备供。', fetch: fetchDevelopmentQuotations, detail: fetchDevelopmentQuotation,
    columns: [
      { key: 'project_no', label: '开发编码', minWidth: 170 }, { key: 'supplier_name', label: '供应商', minWidth: 160 }, { key: 'quoted_cost', label: '报价' },
      { key: 'moq', label: 'MOQ' }, { key: 'is_primary', label: '供货角色' }, { key: 'status', label: '状态' }, { key: 'created_at', label: '报价时间', minWidth: 150 }
    ]
  },
  costs: {
    title: '成本核算', subtitle: '按开发方式和测款模式核算落地成本、目标毛利及开发投入分摊。', fetch: (params) => fetchDevelopmentProjects({ ...params, view: 'costs' }),
    columns: [
      { key: 'project_no', label: '开发编码', minWidth: 170 }, { key: 'product_name', label: '商品名称', minWidth: 190 }, { key: 'landed_cost', label: '落地成本' },
      { key: 'development_cost', label: '开发投入' }, { key: 'estimated_margin_rate', label: '预计毛利率' }, { key: 'status', label: '状态' }, { key: 'updated_at', label: '更新时间', minWidth: 150 }
    ]
  },
  listingDecisions: {
    title: '上架决策', subtitle: '汇总样品、比价和成本信息后形成一次明确的上架决策。', fetch: fetchDevelopmentListingDecisions, detail: fetchDevelopmentListingDecision,
    columns: [
      { key: 'project_no', label: '开发编码', minWidth: 170 }, { key: 'product_name', label: '商品名称', minWidth: 190 }, { key: 'decision', label: '决策结论' },
      { key: 'estimated_margin_rate', label: '预计毛利率' }, { key: 'decided_by_name', label: '决策人' }, { key: 'status', label: '状态' }, { key: 'decided_at', label: '决策时间', minWidth: 150 }
    ]
  },
  trials: {
    title: '首单与试销', subtitle: '按实际小单和虚拟库存两种模式记录试销，并按模式应用不同指标基准。', notice: '实际小单测款达标可直接转正；虚拟库存测款达标后先进入上新计划，实际准备上新时再转正。', fetch: fetchDevelopmentTrials, detail: fetchDevelopmentTrial,
    columns: [
      { key: 'project_no', label: '开发编码', minWidth: 170 }, { key: 'product_name', label: '商品名称', minWidth: 190 }, { key: 'trial_mode', label: '测款模式' },
      { key: 'trial_period', label: '试销周期' }, { key: 'conversion_rate', label: '下单转化' }, { key: 'trial_status', label: '试销状态' }, { key: 'updated_at', label: '更新时间', minWidth: 150 }
    ]
  },
  reorderDecisions: {
    title: '返单决策', subtitle: '记录追单、放弃和观察决策，并跟踪交期窗口。', fetch: fetchDevelopmentReorderDecisions, detail: fetchDevelopmentReorderDecision,
    columns: [
      { key: 'project_no', label: '开发编码', minWidth: 170 }, { key: 'product_name', label: '商品名称', minWidth: 190 }, { key: 'decision', label: '返单结论' },
      { key: 'suggested_qty', label: '建议数量' }, { key: 'lead_time_days', label: '交期（天）' }, { key: 'status', label: '状态' }, { key: 'decided_at', label: '决策时间', minWidth: 150 }
    ]
  },
  eliminations: {
    title: '淘汰库', subtitle: '永久保留各阶段淘汰记录、原因和关联事件，用于开发复盘。', fetch: fetchDevelopmentEliminations, detail: fetchDevelopmentElimination,
    columns: [
      { key: 'project_no', label: '开发编码', minWidth: 170 }, { key: 'product_name', label: '商品名称', minWidth: 190 }, { key: 'elimination_stage', label: '淘汰阶段' },
      { key: 'reason', label: '淘汰原因', minWidth: 220 }, { key: 'development_type', label: '开发类型' }, { key: 'eliminated_by_name', label: '操作人' }, { key: 'eliminated_at', label: '淘汰时间', minWidth: 150 }
    ]
  },
  settings: {
    title: '开发设置', subtitle: '维护编码规则、成本公式、测款指标、事件规则和流程模板。', fetch: fetchDevelopmentSettings, detail: fetchDevelopmentSetting,
    columns: [
      { key: 'key', label: '配置项', minWidth: 190 }, { key: 'label', label: '名称', minWidth: 190 }, { key: 'value', label: '当前值', minWidth: 220 },
      { key: 'scope', label: '适用范围' }, { key: 'status', label: '状态' }, { key: 'updated_at', label: '更新时间', minWidth: 150 }
    ]
  }
};

const canonicalMode = computed(() => modeAliases[props.mode] || props.mode || 'candidates');
const activeConfig = computed(() => modeConfigs[canonicalMode.value] || modeConfigs.candidates);
const meta = computed(() => activeConfig.value);
const rows = ref([]); const loading = ref(false); const saving = ref(false); const search = ref(''); const statusFilter = ref('');
const drawerOpen = ref(false); const selected = ref(null); const candidateOpen = ref(false); const candidateFormRef = ref(null); const categories = ref([]); const suppliers = ref([]);
const candidate = reactive({ product_name: '', development_type: 'factory_selection', trial_mode: 'small_order', category_node: null, original_model: '', design_file_reference: '', design_sent_date: '', supplier: null, planned_launch_date: '', development_reason: '' });
const developmentTypes = [{ value: 'factory_selection', label: '工厂选款' }, { value: 'self_design', label: '自有设计（轻量）' }, { value: 'micro_revision', label: '微改款（预留）' }];
const trialModes = [{ value: 'small_order', label: '实际小单测款' }, { value: 'virtual', label: '虚拟库存测款' }];
const statusLabels = { draft: '草稿', pending: '待处理', pending_review: '待评审', active: '进行中', in_progress: '进行中', approved: '已通过', passed: '已通过', completed: '已完成', confirmed: '已确认', rejected: '已退回', eliminated: '已淘汰', cancelled: '已取消', suspended: '已挂起', terminated: '已终止', virtual: '虚拟测款', formalized: '已转正' };
const fieldLabels = { candidate_no: '开发编码', project_no: '开发编码', product_name: '商品名称', name: '名称', development_type: '开发类型', trial_mode: '测款模式', category_node: '分类 ID', category_path: '商品分类', category_name: '分类', original_model: '工厂原型号', supplier: '来源工厂', supplier_name: '供应商', quoted_cost: '报价', landed_cost: '落地成本', development_cost: '开发投入', estimated_margin_rate: '预计毛利率', status: '状态', trial_status: '试销状态', decision: '决策结论', reason: '原因', development_reason: '开发理由', elimination_stage: '淘汰阶段', created_at: '创建时间', updated_at: '更新时间', received_at: '收样日期', decided_at: '决策时间', eliminated_at: '淘汰时间', scope: '适用范围', value: '当前值' };

const categoryOptions = computed(() => {
  const byId = new Map(categories.value.map((item) => [Number(item.id), item]));
  const pathFor = (item) => {
    const parts = []; const seen = new Set(); let current = item;
    while (current && !seen.has(Number(current.id))) { seen.add(Number(current.id)); parts.unshift(`L${current.level} ${current.code || ''} ${current.name || ''}`.trim()); current = byId.get(Number(current.parent)); }
    return parts.join(' / ');
  };
  return categories.value.filter((item) => item.is_active !== false && [2, 3].includes(Number(item.level))).map((item) => ({ ...item, path: pathFor(item) }));
});
const supplierOptions = computed(() => suppliers.value.filter((item) => item.status ? item.status === 'active' : item.is_active !== false));
const statusOptions = computed(() => [...new Set(rows.value.map((row) => valueFor(row, 'status') || valueFor(row, 'trial_status')).filter(Boolean))].map((value) => ({ value, label: formatStatus(value) })));
const filteredRows = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  return rows.value.filter((row) => {
    const text = [row.candidate_no, row.project_no, row.product_name, row.name, row.supplier_name, row.competitor_name].filter(Boolean).join(' ').toLowerCase();
    const rowStatus = valueFor(row, 'status') || valueFor(row, 'trial_status');
    return (!keyword || text.includes(keyword)) && (!statusFilter.value || rowStatus === statusFilter.value);
  });
});
const metrics = computed(() => {
  const values = rows.value.map((row) => valueFor(row, 'status') || valueFor(row, 'trial_status'));
  const activeCount = values.filter((value) => ['active', 'in_progress', 'pending', 'pending_review', 'draft'].includes(value)).length;
  const completedCount = values.filter((value) => ['completed', 'approved', 'passed', 'confirmed', 'formalized'].includes(value)).length;
  return [{ label: '当前记录', value: rows.value.length, note: '当前筛选范围' }, { label: '待处理', value: activeCount, note: '需继续推进' }, { label: '已完成', value: completedCount, note: '已形成结果' }];
});
const detailRows = computed(() => {
  if (!selected.value) return [];
  const hidden = new Set(['id', 'events', 'created_by', 'updated_by', 'tenant', 'project', 'category_node']);
  return Object.entries(selected.value).filter(([key, value]) => !hidden.has(key) && value !== null && value !== undefined && value !== '').slice(0, 28).map(([key, value]) => ({ key, label: fieldLabels[key] || key, value }));
});
const emptyDescription = computed(() => loading.value ? '正在加载' : `${meta.value.title}暂无记录`);
const candidateRules = {
  product_name: [{ required: true, message: '请输入商品名称', trigger: 'blur' }], development_type: [{ required: true, message: '请选择开发类型', trigger: 'change' }], trial_mode: [{ required: true, message: '请选择测款模式', trigger: 'change' }], category_node: [{ required: true, message: '请选择 L2 或 L3 分类', trigger: 'change' }],
  original_model: [{ validator: (_rule, value, callback) => candidate.development_type !== 'self_design' && !String(value || '').trim() ? callback(new Error('工厂选款/微改款必须填写原型号')) : callback(), trigger: 'blur' }],
  design_files: [{ validator: (_rule, value, callback) => candidate.development_type === 'self_design' && !String(candidate.design_file_reference || '').trim() ? callback(new Error('自有设计必须填写设计附件')) : callback(), trigger: 'blur' }],
  design_sent_date: [{ validator: (_rule, value, callback) => candidate.development_type === 'self_design' && !value ? callback(new Error('自有设计必须填写设计稿发送日期')) : callback(), trigger: 'change' }]
};

function collectionFrom(response) {
  if (Array.isArray(response?.data)) return response.data;
  if (Array.isArray(response?.data?.results)) return response.data.results;
  if (Array.isArray(response?.data?.items)) return response.data.items;
  if (Array.isArray(response?.results)) return response.results;
  if (response?.data && typeof response.data === 'object' && response.data.id) return [response.data];
  return [];
}
function valueFor(row, key) {
  if (!row || !key) return undefined;
  const aliases = { category_path: ['category_path', 'category_name', 'category'], product_name: ['product_name', 'name', 'title'], project_no: ['project_no', 'candidate_no', 'development_no'], supplier_name: ['supplier_name', 'supplier', 'factory_name'], status: ['status', 'state'] };
  return (aliases[key] || [key]).map((candidateKey) => row[candidateKey]).find((value) => value !== null && value !== undefined && value !== '');
}
function formatStatus(value) { if (value === 'factory_selection') return '工厂选款'; if (value === 'self_design') return '自有设计'; if (value === 'micro_revision') return '微改款'; if (value === 'small_order') return '实际小单测款'; if (value === 'virtual') return '虚拟库存测款'; return statusLabels[value] || value || '—'; }
function formatCell(value) { if (value === null || value === undefined || value === '') return '—'; if (typeof value === 'boolean') return value ? '是' : '否'; if (Array.isArray(value)) return value.join(' / '); if (typeof value === 'object') return JSON.stringify(value); return String(value); }
function statusType(value) { if (['completed', 'approved', 'passed', 'confirmed', 'formalized'].includes(value)) return 'success'; if (['rejected', 'eliminated', 'terminated', 'cancelled'].includes(value)) return 'danger'; if (['pending', 'pending_review', 'active', 'in_progress', 'draft', 'suspended'].includes(value)) return 'warning'; return 'info'; }
async function refresh() { loading.value = true; const response = await activeConfig.value.fetch({ search: search.value.trim(), status: statusFilter.value, page: 1, page_size: 100 }); rows.value = collectionFrom(response); loading.value = false; if (!response?.success) ElMessage.error(response?.message || `${meta.value.title}加载失败`); }
async function selectRow(row) { selected.value = row; drawerOpen.value = true; if (activeConfig.value.detail && row?.id) { const response = await activeConfig.value.detail(row.id); if (response?.success && response.data) selected.value = response.data; } }
async function loadCategories() { const response = await fetchProductCategories({ page: 1, page_size: 100 }); if (response?.success) categories.value = collectionRows(response.data); }
async function loadSuppliers() { const response = await fetchSupplierMasters({ page: 1, page_size: 100, status: 'active' }); if (response?.success) suppliers.value = collectionRows(response.data); }
function openCandidateForm() { Object.assign(candidate, { product_name: '', development_type: 'factory_selection', trial_mode: 'small_order', category_node: null, original_model: '', design_file_reference: '', design_sent_date: '', supplier: null, planned_launch_date: '', development_reason: '' }); candidateOpen.value = true; loadCategories(); loadSuppliers(); }
function onDevelopmentTypeChange(value) { if (value === 'self_design') candidate.original_model = '无（自有设计）'; else if (candidate.original_model === '无（自有设计）') candidate.original_model = ''; }
async function saveCandidate() { const valid = await candidateFormRef.value?.validate().catch(() => false); if (!valid) return; saving.value = true; const payload = { product_name: String(candidate.product_name || '').trim(), development_type: candidate.development_type, trial_mode: candidate.trial_mode, category_node: Number(candidate.category_node), original_model: candidate.development_type === 'self_design' ? '无（自有设计）' : String(candidate.original_model || '').trim(), design_files: candidate.development_type === 'self_design' ? String(candidate.design_file_reference || '').split(',').map((item) => item.trim()).filter(Boolean) : [], design_sent_date: candidate.development_type === 'self_design' ? candidate.design_sent_date : null, supplier: candidate.supplier ? Number(candidate.supplier) : null, planned_launch_date: candidate.planned_launch_date || null, development_reason: String(candidate.development_reason || '').trim() }; const response = await createDevelopmentCandidate(payload); saving.value = false; if (!response?.success) return ElMessage.error(response?.message || '候选款保存失败'); candidateOpen.value = false; ElMessage.success('候选款已保存'); await refresh(); }
onMounted(refresh);
</script>

<style scoped>
.dev-page { min-width: 980px; color: #172033; }
.dev-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }
.dev-header h1 { margin: 0; font-size: 26px; }
.dev-header p { margin: 7px 0 0; color: #64748b; }
.dev-actions { display: flex; gap: 10px; }
.dev-notice { margin-bottom: 16px; }
.metric-strip { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid #dbe3ee; border-radius: 8px; background: #fff; margin-bottom: 16px; }
.metric { padding: 18px 20px; border-right: 1px solid #e6ebf2; }
.metric:last-child { border-right: 0; }
.metric span, .metric small { display: block; color: #718096; font-size: 12px; }
.metric strong { display: block; margin: 7px 0 5px; font-size: 25px; color: #172033; }
.work-panel { border: 1px solid #dbe3ee; border-radius: 8px; background: #fff; overflow: hidden; }
.filter-row { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid #e6ebf2; }
.filter-row .el-input { width: 300px; }
.filter-row .el-select { width: 160px; }
.filter-spacer { flex: 1; }
.result-count { color: #718096; font-size: 12px; }
.dev-table { width: 100%; }
.drawer-title { display: flex; gap: 12px; align-items: center; margin-bottom: 20px; }
.drawer-title h3, .drawer-title p { margin: 0; }
.drawer-title p { margin-top: 5px; color: #718096; }
.record-avatar { display: grid; place-items: center; width: 48px; height: 48px; border: 1px solid #dbe3ee; border-radius: 7px; background: #f5f8fc; color: #2563eb; font-size: 20px; font-weight: 700; }
.form-notice { margin-bottom: 18px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.field-help { display: block; margin-top: 4px; color: #64748b; line-height: 1.4; }
@media (max-width: 1100px) { .dev-page { min-width: 0; } }
@media (max-width: 800px) { .metric-strip { grid-template-columns: 1fr; } .metric { border-right: 0; border-bottom: 1px solid #e6ebf2; } .metric:last-child { border-bottom: 0; } .dev-header { gap: 12px; } .filter-row { flex-wrap: wrap; } .filter-row .el-input, .filter-row .el-select { width: 100%; } .filter-spacer { display: none; } .form-grid { grid-template-columns: 1fr; } }
</style>
