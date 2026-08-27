<template>
  <section class="sample-page">
    <header class="page-hero">
      <div>
        <span>FULFILLMENT DESK</span>
        <h1>送样履约</h1>
        <p>跟踪建联达人从待发样到内容交付的完整履约过程。</p>
      </div>
    </header>

    <div class="metrics">
      <div><span>当前记录</span><strong>{{ displayValue(total) }}</strong></div>
      <div><span>已进入履约</span><strong>{{ displayValue(fulfilledCount) }}</strong></div>
      <div><span>待发样</span><strong>{{ displayValue(pendingCount) }}</strong></div>
      <div><span>异常/取消</span><strong>{{ displayValue(exceptionCount) }}</strong></div>
    </div>

    <el-card class="workspace-card" shadow="never">
      <div class="toolbar">
        <el-input v-model="filters.search" clearable placeholder="搜索达人/送样编号/建联编号/产品/订单" @keyup.enter="applyFilters" />
        <el-select v-model="filters.store" clearable filterable placeholder="全部店铺">
          <el-option v-for="store in rowStores" :key="store.id" :label="store.name" :value="store.id" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="全部状态">
          <el-option v-for="(label, value) in FULFILLMENT_STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-checkbox v-model="filters.includeDeleted" @change="applyFilters">显示已删除</el-checkbox>
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button type="primary" :disabled="!canManage" @click="openCreate">新增送样</el-button>
      </div>

      <el-table v-loading="loading" :data="rows" empty-text="暂无送样履约" @row-click="openDetail">
        <el-table-column label="送样 / 建联编号" min-width="175">
          <template #default="{ row }">
            <b>{{ displayValue(row.fulfillment_no) }}</b>
            <small v-if="hasValue(row.outreach_task_no)">建联 {{ row.outreach_task_no }}</small>
            <small v-if="hasValue(row.outreach_task_name)">{{ row.outreach_task_name }}</small>
          </template>
        </el-table-column>
        <el-table-column label="任务 ID" width="100">
          <template #default="{ row }">{{ displayValue(row.outreach_task) }}</template>
        </el-table-column>
        <el-table-column label="达人" min-width="150">
          <template #default="{ row }">
            <b>{{ displayValue(row.influencer_name || row.influencer) }}</b>
            <small v-if="hasValue(row.influencer)">ID {{ row.influencer }}</small>
          </template>
        </el-table-column>
        <el-table-column label="店铺" min-width="130">
          <template #default="{ row }">{{ displayValue(row.store_name || row.store) }}</template>
        </el-table-column>
        <el-table-column label="产品 / SKU / 数量" min-width="220">
          <template #default="{ row }">
            <template v-if="row.items?.length">
              <div v-for="item in row.items" :key="item.id || item.requested_sku" class="sku-match">
                <small>{{ displayValue(item.requested_sku || item.matched_sku_code) }} × {{ displayValue(item.quantity) }}</small>
                <div>
                  <el-tag size="small" :type="matchTagType(item.cost_match_status)">{{ statusLabel(COST_MATCH_STATUS_LABELS, item.cost_match_status) }}</el-tag>
                </div>
              </div>
            </template>
            <small v-else>数量 {{ displayValue(row.sku_quantity) }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="external_product_id" label="商品 ID" min-width="155">
          <template #default="{ row }">{{ displayValue(row.external_product_id) }}</template>
        </el-table-column>
        <el-table-column prop="sample_order_no" label="样品订单" min-width="135">
          <template #default="{ row }">{{ displayValue(row.sample_order_no) }}</template>
        </el-table-column>
        <el-table-column label="采购成本" min-width="125">
          <template #default="{ row }">
            <b>{{ displayAmount(row.calculated_cost) }}</b>
            <small>{{ costMatchLabel(row) }}</small>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag>{{ statusLabel(FULFILLMENT_STATUS_LABELS, row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="送样负责人" min-width="130">
          <template #default="{ row }">{{ displayValue(row.owner_name || row.owner) }}</template>
        </el-table-column>
        <el-table-column label="截止 / 视频匹配" min-width="170">
          <template #default="{ row }">
            <small>截止 {{ displayValue(row.video_deadline_at) }}</small>
            <small v-if="row.video_match_count">匹配 {{ row.video_match_count }} 条</small>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">{{ displayValue(row.notes) }}</template>
        </el-table-column>
        <el-table-column label="建联日期" min-width="155">
          <template #default="{ row }">{{ displayValue(outreachDate(row)) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="220" fixed="right">
          <template #default="{ row }">
            <el-button link @click.stop="openDetail(row)">详情</el-button>
            <el-button v-if="canManage && !row.is_deleted" link @click.stop="openEdit(row)">编辑</el-button>
            <el-button v-if="canManage && !row.is_deleted" link type="danger" @click.stop="removeSample(row)">删除</el-button>
            <el-button v-if="canManage && row.is_deleted" link type="primary" @click.stop="restoreSample(row)">恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </el-card>

    <el-dialog
      v-model="visible"
      class="sample-dialog"
      width="720px"
      :close-on-click-modal="false"
      @closed="discardDraft"
    >
      <template #header>
        <div class="dialog-heading">
          <span>送样履约</span>
          <h2>{{ editingSample ? '编辑送样记录' : '新增送样记录' }}</h2>
        </div>
      </template>
      <el-form class="sample-form" label-position="top">
        <div class="form-grid">
          <el-form-item label="送样类型" required class="form-span-2">
            <el-select v-model="form.link_type" :disabled="!!editingSample" placeholder="请选择送样类型">
              <el-option v-for="(label, value) in selectableLinkTypes" :key="value" :label="`${label}（${value}）`" :value="value" />
            </el-select>
            <small class="field-hint">送样编号由系统按类型自动生成，不需要选择建联任务。</small>
          </el-form-item>
          <el-form-item label="送样日期">
            <el-input :model-value="todayLabel" readonly />
          </el-form-item>
          <el-form-item label="达人账号" required>
            <el-select
              v-model="form.influencer"
              filterable
              remote
              allow-create
              default-first-option
              reserve-keyword
              :remote-method="searchInfluencers"
              :loading="influencerLoading"
              :disabled="!!editingSample"
              @change="resolveSelectedInfluencer"
              placeholder="搜索达人账号或名称"
            >
              <el-option v-for="influencer in influencerOptions" :key="influencer.id" :label="influencerLabel(influencer)" :value="influencer.id" />
            </el-select>
            <el-alert v-if="selectedInfluencer?.is_blacklisted" class="blacklist-alert" type="error" :closable="false" title="该达人在黑名单中，不能保存送样。" />
          </el-form-item>
          <el-form-item label="达人 ID">
            <el-input :model-value="displayValue(selectedInfluencer?.id)" readonly />
          </el-form-item>
          <el-form-item label="店铺" required>
            <el-select v-if="!inheritedTask" v-model="form.store" filterable placeholder="请选择店铺">
              <el-option v-for="store in storeOptions" :key="store.id" :label="store.name" :value="store.id" />
            </el-select>
            <el-input v-else :model-value="displayValue(inheritedTask.store_name || inheritedTask.store)" readonly />
          </el-form-item>
          <el-form-item label="样品订单">
            <el-input v-model="form.sample_order_no" placeholder="可填写样品订单号" />
          </el-form-item>
          <el-form-item label="产品 ID" required>
            <el-input v-model="form.external_product_id" :readonly="!!inheritedTask" placeholder="请输入产品 ID" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-if="editingSample" v-model="form.status" placeholder="请选择状态">
              <el-option v-for="status in editableStatusOptions" :key="status" :label="statusLabel(FULFILLMENT_STATUS_LABELS, status)" :value="status" />
            </el-select>
            <el-input v-else model-value="待发样" readonly />
          </el-form-item>
          <el-form-item label="快捷备注标签">
            <el-select v-model="form.quick_tags" multiple filterable allow-create default-first-option placeholder="输入后回车添加标签">
              <el-option v-for="tag in quickTagOptions" :key="tag" :label="tag" :value="tag" />
            </el-select>
          </el-form-item>
          <el-form-item label="SKU 与数量" class="form-span-2">
            <div class="sku-editor">
              <el-alert
                v-if="inheritedTask?.sku_prefix"
                class="price-note"
                type="info"
                :closable="false"
                :title="`任务 SKU 前缀：${inheritedTask.sku_prefix}。请填写实际送样 SKU。`"
              />
              <div class="sku-header"><span>站点</span><span>SKU</span><span>数量</span><span /></div>
              <div v-for="(item, index) in items" :key="index" class="sku-row">
                <el-input v-model="item.site_code" placeholder="站点" />
                <el-input v-model="item.requested_sku" placeholder="SKU 可暂时为空" />
                <el-input-number v-model="item.quantity" :min="1" />
                <el-button link type="danger" :disabled="items.length === 1" @click="items.splice(index, 1)">删除</el-button>
              </div>
              <el-button link type="primary" @click="items.push(newItem())">+ 添加 SKU</el-button>
              <el-alert class="price-note" type="warning" :closable="false" title="采购成本未匹配不会阻止送样记录保存。" />
            </div>
          </el-form-item>
          <el-form-item label="备注" class="form-span-2">
            <el-input v-model="form.notes" type="textarea" :rows="3" placeholder="填写送样备注" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="influencerLoading || selectedInfluencer?.is_blacklisted" :loading="saving" @click="submit">{{ editingSample ? '保存修改' : '保存送样' }}</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" direction="rtl" size="560px" :with-header="false">
      <div class="detail-drawer" v-if="detailSample">
        <div class="drawer-heading"><div><span>送样履约详情</span><h2>{{ displayValue(detailSample.fulfillment_no) }}</h2><small>{{ displayValue(detailSample.outreach_task_name || detailSample.outreach_task_no) }}</small></div><el-button text @click="detailVisible = false">×</el-button></div>
        <el-alert v-if="detailError" class="detail-load-alert" type="warning" :closable="false" :title="detailError" />
        <el-skeleton v-if="detailLoading" :rows="4" animated />
        <div class="drawer-actions">
          <el-button :disabled="!canManage || detailSample.is_deleted" @click="openEdit(detailSample)">编辑</el-button>
          <el-button v-if="!detailSample.is_deleted" type="danger" plain :disabled="!canManage" @click="removeSample(detailSample)">删除</el-button>
          <el-button v-else type="primary" :disabled="!canManage" @click="restoreSample(detailSample)">恢复</el-button>
          <el-tag>{{ statusLabel(FULFILLMENT_STATUS_LABELS, detailSample.status) }}</el-tag>
        </div>
        <section class="detail-section"><h3>送样事实</h3><div class="detail-facts">
          <div><span>达人</span><b>{{ displayValue(detailSample.influencer_name || detailSample.influencer) }}</b></div>
          <div><span>送样负责人</span><b>{{ displayValue(detailSample.owner_name || detailSample.owner) }}</b></div>
          <div><span>店铺</span><b>{{ displayValue(detailSample.store_name || detailSample.store) }}</b></div>
          <div><span>产品 ID</span><b>{{ displayValue(detailSample.external_product_id) }}</b></div>
          <div><span>样品订单</span><b>{{ displayValue(detailSample.sample_order_no) }}</b></div>
          <div><span>建联类型</span><b>{{ statusLabel(FULFILLMENT_LINK_TYPE_LABELS, detailSample.link_type) }}</b></div>
          <div><span>送样时间</span><b>{{ displayValue(detailSample.sample_sent_at) }}</b></div>
          <div><span>发货时间</span><b>{{ displayValue(detailSample.shipped_at) }}</b></div>
          <div><span>视频截止</span><b>{{ displayValue(detailSample.video_deadline_at) }}</b></div>
          <div><span>视频匹配</span><b>{{ detailSample.video_match_count || 0 }} 条</b></div>
        </div><div class="tag-row"><el-tag v-for="tag in detailSample.quick_tags || []" :key="tag" size="small">{{ tag }}</el-tag></div><p class="detail-note">{{ displayValue(detailSample.notes) }}</p></section>
        <section class="detail-section"><h3>SKU 明细</h3><div v-if="detailSample.items?.length" class="sku-detail-list"><p v-for="item in detailSample.items" :key="item.id || `${item.site_code}-${item.requested_sku}`">{{ displayValue(item.requested_sku) }} × {{ displayValue(item.quantity) }}</p></div><div v-else class="empty-state">暂无 SKU 明细</div></section>
        <section class="detail-section"><h3>采购成本</h3><div class="detail-facts">
          <div><span>采购成本</span><b>{{ displayAmount(detailSample.calculated_cost) }}</b></div>
          <div><span>成本匹配</span><b>{{ costMatchLabel(detailSample) }}</b></div>
        </div></section>
        <section class="detail-section"><h3>视频匹配结果</h3><div v-if="detailSample.video_matches?.length" class="video-list"><p v-for="video in detailSample.video_matches" :key="video.id">{{ displayValue(video.title || video.external_content_id) }} · {{ displayValue(video.published_at) }}</p></div><div v-else class="empty-state">暂无已发布匹配视频</div></section>
      </div>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import {
  COST_MATCH_STATUS_LABELS,
  createSampleFulfillment,
  deleteSampleFulfillment,
  fetchOutreachTask,
  fetchOutreachTaskOptions,
  fetchInfluencerResolve,
  fetchSampleFulfillment,
  fetchSampleFulfillmentOptions,
  fetchSampleFulfillments,
  formatInfluencerError,
  FULFILLMENT_LINK_TYPE_LABELS,
  FULFILLMENT_STATUS_LABELS,
  FULFILLMENT_STATUS_TRANSITIONS,
  restoreSampleFulfillment,
  resolveOrCreateInfluencer,
  statusLabel,
  updateSampleFulfillment
} from '../../api/influencers';
import { collectionRows, collectionTotal, detailData } from '../../utils/businessResponse';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const rows = ref([]);
const tasks = ref([]);
const storeOptions = ref([]);
const influencerOptions = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const saving = ref(false);
const influencerLoading = ref(false);
const visible = ref(false);
const detailVisible = ref(false);
const detailSample = ref(null);
const detailLoading = ref(false);
const detailError = ref('');
const editingSample = ref(null);
const inheritedTask = ref(null);
const draftKey = ref('');
const filters = reactive({ search: '', status: '', store: null, includeDeleted: false });
const form = reactive({ outreach_task: null, influencer: null, store: null, product_name_snapshot: '', external_product_id: '', sample_order_no: '', notes: '', link_type: 'YYJL', quick_tags: [], status: 'pending' });
const QUICK_TAG_PRESETS = Object.freeze(['BD建联', '运营建联', '直播达人', '已完成', '已拉黑']);
const quickTagOptions = computed(() => [...new Set([...QUICK_TAG_PRESETS, ...form.quick_tags])]);
const selectableLinkTypes = computed(() => inheritedTask.value
  ? { DRJL: FULFILLMENT_LINK_TYPE_LABELS.DRJL }
  : Object.fromEntries(Object.entries(FULFILLMENT_LINK_TYPE_LABELS).filter(([value]) => value !== 'DRJL')));
const newItem = () => ({ site_code: 'PH', external_product_id: '', requested_sku: null, quantity: 1 });
const items = ref([newItem()]);
const canManage = computed(() => auth.hasPermission('influencers.fulfillment.manage'));
const fulfilledStatuses = ['shipped', 'delivered', 'received', 'creating', 'published', 'completed', 'live_creator'];
const fulfilledCount = computed(() => rows.value.filter((row) => fulfilledStatuses.includes(row.status) || row.shipped_at || row.sample_order_no).length);
const pendingCount = computed(() => rows.value.filter((row) => row.status === 'pending').length);
const exceptionCount = computed(() => rows.value.filter((row) => ['overdue', 'cancelled'].includes(row.status)).length);
const rowStores = computed(() => [...new Map(rows.value.filter((row) => row.store).map((row) => [row.store, { id: row.store, name: row.store_name || `店铺 ${row.store}` }])).values()]);
const hasValue = (value) => value !== undefined && value !== null && value !== '';
const displayValue = (value) => hasValue(value) ? String(value) : '—';
const selectedInfluencer = computed(() => influencerOptions.value.find((influencer) => String(influencer.id) === String(form.influencer)) || null);
const editableStatusOptions = computed(() => {
  const current = editingSample.value?.status || 'pending';
  return [...new Set([current, ...(FULFILLMENT_STATUS_TRANSITIONS[current] || [])])];
});
let influencerResolveSequence = 0;
let sampleSubmitSequence = 0;

function normalizeInfluencerAccount(value) {
  return String(value ?? '').normalize('NFKC').trim().replace(/^@+/, '').trim().toLowerCase();
}

function influencerAccountKey(influencer) {
  for (const value of [influencer?.handle, influencer?.code]) {
    const normalized = normalizeInfluencerAccount(value);
    if (normalized) return normalized;
  }
  return '';
}

function isBlacklistedInfluencer(influencer) {
  const value = influencer?.is_blacklisted ?? influencer?.blacklisted;
  return value === true || value === 1 || value === 'true';
}

function influencerInformationScore(influencer) {
  return Object.entries(influencer || {}).reduce((score, [field, value]) => {
    if (field === 'id' || field === 'is_blacklisted' || field === 'blacklisted') return score;
    return score + (hasValue(value) ? 1 : 0);
  }, 0);
}

function shouldPreferInfluencer(candidate, current) {
  const candidateBlacklisted = isBlacklistedInfluencer(candidate);
  const currentBlacklisted = isBlacklistedInfluencer(current);
  if (candidateBlacklisted !== currentBlacklisted) return candidateBlacklisted;
  return influencerInformationScore(candidate) > influencerInformationScore(current);
}

function dedupeInfluencerCandidates(candidates = []) {
  const unique = [];
  const indexesByAccount = new Map();
  for (const candidate of Array.isArray(candidates) ? candidates : []) {
    const account = influencerAccountKey(candidate);
    if (!account) {
      unique.push(candidate);
      continue;
    }
    const currentIndex = indexesByAccount.get(account);
    if (currentIndex === undefined) {
      indexesByAccount.set(account, unique.length);
      unique.push(candidate);
    } else if (shouldPreferInfluencer(candidate, unique[currentIndex])) {
      unique[currentIndex] = candidate;
    }
  }
  return unique;
}

function responseInfluencerCandidates(response) {
  return dedupeInfluencerCandidates([
    ...(Array.isArray(response?.data?.candidates) ? response.data.candidates : []),
    ...(Array.isArray(response?.data?.results) ? response.data.results : [])
  ]);
}

const todayLabel = (() => {
  const today = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
})();

async function load() {
  loading.value = true;
  const params = { page: page.value, page_size: pageSize.value, search: filters.search, status: filters.status, store: filters.store };
  if (filters.includeDeleted) params.include_deleted = 'true';
  const r = await fetchSampleFulfillments(params);
  loading.value = false;
  if (r.success) {
    rows.value = collectionRows(r.data);
    total.value = collectionTotal(r.data);
  } else {
    ElMessage.error(formatInfluencerError(r, '送样列表加载失败'));
  }
}

function applyFilters() {
  page.value = 1;
  load();
}

function resetFilters() {
  Object.assign(filters, { search: '', status: '', store: null, includeDeleted: false });
  applyFilters();
}

const newKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
function discardDraft() {
  influencerResolveSequence += 1;
  sampleSubmitSequence += 1;
  influencerLoading.value = false;
  saving.value = false;
  draftKey.value = '';
  clearEditor();
}

function clearEditor() {
  editingSample.value = null;
  inheritedTask.value = null;
  items.value = [newItem()];
}

function queryValue(primary, fallback) {
  const value = route.query?.[primary] ?? route.query?.[fallback];
  return Array.isArray(value) ? value[0] : value;
}

function querySelection() {
  return {
    taskId: queryValue('outreach_task', 'task')
  };
}

async function consumeTaskQuery() {
  if (!queryValue('outreach_task', 'task')) return;
  const query = { ...route.query };
  delete query.outreach_task;
  delete query.task;
  await router.replace({ query });
}

async function findTask(taskId) {
  let task = tasks.value.find((item) => String(item.id) === String(taskId));
  if (task) return task;
  const r = await fetchOutreachTask(taskId);
  if (!r.success) return null;
  task = detailData(r.data);
  if (!task.id || ['completed', 'cancelled'].includes(task.status)) return null;
  tasks.value = [task, ...tasks.value];
  return task;
}

async function openCreate(selection = {}) {
  influencerResolveSequence += 1;
  sampleSubmitSequence += 1;
  influencerLoading.value = false;
  saving.value = false;
  editingSample.value = null;
  Object.assign(form, {
    outreach_task: null,
    influencer: null,
    store: null,
    product_name_snapshot: '',
    external_product_id: '',
    sample_order_no: '',
    notes: '',
    link_type: 'YYJL',
    quick_tags: [],
    status: 'pending'
  });
  inheritedTask.value = null;
  items.value = [newItem()];
  draftKey.value = newKey();
  const [optionResponse, taskOptionResponse] = await Promise.all([
    fetchSampleFulfillmentOptions(),
    fetchOutreachTaskOptions()
  ]);
  tasks.value = optionResponse.success ? (optionResponse.data?.tasks || []) : [];
  storeOptions.value = taskOptionResponse.success ? (taskOptionResponse.data?.stores || []) : [];
  influencerOptions.value = optionResponse.success
    ? dedupeInfluencerCandidates(optionResponse.data?.influencers || [])
    : [];
  if (!optionResponse.success) ElMessage.error(formatInfluencerError(optionResponse, '达人账号加载失败'));
  const routeSelection = querySelection();
  const requested = { ...routeSelection, ...(selection?.taskId ? selection : {}) };
  if (routeSelection.taskId) await consumeTaskQuery();
  if (requested.taskId) {
    const task = await findTask(requested.taskId);
    if (task) {
      form.outreach_task = task.id;
      await selectTask(task.id);
    }
  }
  visible.value = true;
}

async function selectTask(id) {
  inheritedTask.value = tasks.value.find((item) => String(item.id) === String(id)) || null;
  if (!id) inheritedTask.value = null;
  if (inheritedTask.value) {
    form.link_type = 'DRJL';
    form.store = inheritedTask.value.store;
    form.product_name_snapshot = inheritedTask.value.task_name || inheritedTask.value.external_product_id || '';
    form.external_product_id = inheritedTask.value.external_product_id || '';
  }
}

function influencerLabel(influencer) {
  const account = influencer.handle || influencer.code || `达人 ${influencer.id}`;
  const suffix = [influencer.name, influencer.platform].filter(hasValue).join(' · ');
  return suffix ? `${account}（${suffix}）` : account;
}

async function searchInfluencers(search) {
  const sequence = ++influencerResolveSequence;
  influencerLoading.value = true;
  const response = await fetchInfluencerResolve(String(search || '').trim());
  if (sequence !== influencerResolveSequence) return;
  influencerLoading.value = false;
  if (!response.success) return ElMessage.error(formatInfluencerError(response, '达人账号搜索失败'));
  influencerOptions.value = responseInfluencerCandidates(response);
}

async function resolveSelectedInfluencer(id) {
  const sequence = ++influencerResolveSequence;
  const selected = influencerOptions.value.find((item) => String(item.id) === String(id));
  if (!selected) {
    const account = String(id || '').trim().replace(/^@+/, '');
    if (!account) {
      influencerLoading.value = false;
      return;
    }
    influencerLoading.value = true;
    const created = await resolveOrCreateInfluencer(account);
    if (sequence !== influencerResolveSequence) return;
    influencerLoading.value = false;
    if (!created.success) {
      form.influencer = null;
      return ElMessage.error(formatInfluencerError(created, '达人账号解析失败'));
    }
    const resolved = created.data;
    influencerOptions.value = dedupeInfluencerCandidates([resolved, ...influencerOptions.value]);
    const resolvedAccount = influencerAccountKey(resolved);
    const selected = influencerOptions.value.find((item) => (
      String(item.id) === String(resolved.id)
      || (resolvedAccount && influencerAccountKey(item) === resolvedAccount)
    ));
    form.influencer = selected?.id ?? resolved.id;
    if (resolved.created) ElMessage.success('已自动建立达人档案');
    return;
  }
  influencerLoading.value = true;
  const response = await fetchInfluencerResolve(selected.handle || selected.code || selected.name);
  if (sequence !== influencerResolveSequence) return;
  influencerLoading.value = false;
  if (!response.success) return ElMessage.error(formatInfluencerError(response, '达人账号校验失败'));
  const selectedAccount = influencerAccountKey(selected);
  const resolved = responseInfluencerCandidates(response).find((item) => (
    String(item.id) === String(id)
    || (selectedAccount && influencerAccountKey(item) === selectedAccount)
  ));
  if (resolved) {
    influencerOptions.value = dedupeInfluencerCandidates([
      resolved,
      selected,
      ...influencerOptions.value.filter((item) => String(item.id) !== String(id))
    ]);
    const preferred = influencerOptions.value.find((item) => (
      String(item.id) === String(resolved.id)
      || (selectedAccount && influencerAccountKey(item) === selectedAccount)
    ));
    form.influencer = preferred?.id ?? resolved.id;
  }
}

function outreachDate(row) {
  return row.outreach_at || row.first_linked_at || '—';
}

function displayAmount(value) {
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

function costMatchLabel(row) {
  const statuses = (row?.items || []).map((item) => item.cost_match_status).filter(hasValue);
  if (!statuses.length) return '采购成本待匹配';
  const unmatched = statuses.find((status) => !String(status).startsWith('matched'));
  return statusLabel(COST_MATCH_STATUS_LABELS, unmatched || statuses[0]);
}

function matchTagType(status) {
  if (status === 'matched' || String(status || '').startsWith('matched_')) return 'success';
  if (['pending', 'not_imported'].includes(status)) return 'warning';
  return 'danger';
}

async function openDetail(row) {
  detailSample.value = { ...row };
  detailVisible.value = true;
  detailLoading.value = true;
  detailError.value = '';
  const response = await fetchSampleFulfillment(row.id, { include_deleted: row.is_deleted ? 'true' : undefined });
  detailLoading.value = false;
  const detail = response.success ? detailData(response.data) : {};
  if (response.success) {
    detailSample.value = mergeDetailFacts(row, detail);
    return;
  }
  detailError.value = formatInfluencerError(response, '送样详情加载失败，当前展示列表已有数据');
  ElMessage.error(detailError.value);
}

function mergeDetailFacts(base = {}, detail = {}) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(detail || {})) {
    if (value === undefined) continue;
    merged[key] = value;
  }
  return merged;
}

async function openEdit(row) {
  if (!canManage.value || row.is_deleted) return;
  influencerResolveSequence += 1;
  sampleSubmitSequence += 1;
  influencerLoading.value = false;
  saving.value = false;
  editingSample.value = { ...row };
  Object.assign(form, {
    outreach_task: row.outreach_task,
    influencer: row.influencer,
    store: row.store,
    product_name_snapshot: row.product_name_snapshot || '',
    external_product_id: row.external_product_id || '',
    sample_order_no: row.sample_order_no || '',
    notes: row.notes || '',
    link_type: row.link_type || 'DRJL',
    quick_tags: [...(row.quick_tags || [])],
    status: row.status || 'pending'
  });
  influencerOptions.value = dedupeInfluencerCandidates([{
    id: row.influencer,
    name: row.influencer_name,
    code: row.influencer_code,
    handle: row.influencer_handle,
    platform: row.influencer_platform,
    is_blacklisted: row.is_blacklisted
  }]);
  inheritedTask.value = row;
  items.value = row.items?.length ? row.items.map((item) => ({ ...item })) : [newItem()];
  visible.value = true;
}

async function removeSample(row) {
  if (!canManage.value || row.is_deleted) return;
  try {
    await ElMessageBox.confirm('删除后可在“显示已删除”中恢复，确认删除该送样吗？', '确认删除', { type: 'warning' });
  } catch {
    return;
  }
  const response = await deleteSampleFulfillment(row.id, row.version);
  if (!response.success) return ElMessage.error(formatInfluencerError(response));
  ElMessage.success('送样已删除');
  detailVisible.value = false;
  await load();
}

async function restoreSample(row) {
  if (!canManage.value || !row.is_deleted) return;
  const response = await restoreSampleFulfillment(row.id, row.version);
  if (!response.success) return ElMessage.error(formatInfluencerError(response));
  ElMessage.success('送样已恢复');
  await load();
}

async function submit() {
  if (influencerLoading.value) return ElMessage.warning('达人账号仍在校验，请稍候');
  if (!form.influencer || !form.store || !form.external_product_id.trim()) return ElMessage.warning('请填写达人、店铺和产品 ID');
  if (selectedInfluencer.value?.is_blacklisted) return ElMessage.error('该达人在黑名单中，不能保存送样');
  if (editingSample.value) return submitEdit();
  const sequence = ++sampleSubmitSequence;
  saving.value = true;
  const payload = {
    ...(form.outreach_task ? { outreach_task: form.outreach_task } : {}),
    influencer: form.influencer,
    store: form.store,
    product_name_snapshot: form.product_name_snapshot.trim() || form.external_product_id.trim(),
    external_product_id: form.external_product_id.trim(),
    sample_order_no: form.sample_order_no,
    notes: form.notes,
    link_type: form.link_type,
    quick_tags: form.quick_tags,
    items: items.value.map((item) => ({
      ...item,
      external_product_id: inheritedTask.value?.external_product_id || '',
      requested_sku: item.requested_sku?.trim() || null
    }))
  };
  const r = await createSampleFulfillment(payload, draftKey.value);
  if (sequence !== sampleSubmitSequence) return;
  saving.value = false;
  if (!r.success) return ElMessage.error(formatInfluencerError(r, '送样创建失败'));
  draftKey.value = '';
  visible.value = false;
  ElMessage.success('送样已创建');
  load();
}

async function submitEdit() {
  const sequence = ++sampleSubmitSequence;
  const editedSample = { ...editingSample.value };
  saving.value = true;
  const response = await updateSampleFulfillment(editedSample.id, {
    sample_order_no: form.sample_order_no,
    notes: form.notes,
    link_type: form.link_type,
    quick_tags: form.quick_tags,
    status: form.status,
    items: items.value.map((item) => ({
      site_code: item.site_code,
      requested_sku: item.requested_sku?.trim() || null,
      quantity: item.quantity,
      external_product_id: editedSample.external_product_id || ''
    })),
    items_mode: 'replace'
  }, editedSample.version);
  if (sequence !== sampleSubmitSequence) return;
  saving.value = false;
  if (!response.success) return ElMessage.error(formatInfluencerError(response, '送样修改失败'));
  visible.value = false;
  detailVisible.value = false;
  ElMessage.success('送样已修改');
  await load();
}

onMounted(async () => {
  await load();
  if (canManage.value) {
    const selection = querySelection();
    if (selection.taskId) await openCreate(selection);
  }
});
</script>

<style scoped>
.sample-page { display: grid; gap: 18px; }
.sample-page .page-hero { display: flex; justify-content: space-between; align-items: end; padding: 24px; border-radius: 16px; background: linear-gradient(120deg, #0b5345, #167d68); color: #fff; }
.page-hero h1 { margin: 6px 0; }
.page-hero p { margin: 0; opacity: .82; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; overflow: hidden; }
.metrics div { padding: 15px 18px; border-right: 1px solid #e5e7eb; }
.metrics div:last-child { border: 0; }
.metrics span, .metrics strong, td small, .sku-match small { display: block; }
.metrics span, td small, .sku-match small { color: #84909c; font-size: 12px; }
.metrics strong { margin-top: 5px; font-size: 24px; color: #1f2937; }
.toolbar { display: flex; flex-wrap: nowrap; align-items: center; gap: 10px; margin-bottom: 16px; overflow-x: auto; }
.toolbar .el-input { flex: 1 1 460px; min-width: 300px; }
.toolbar .el-select { flex: 0 0 145px; width: 145px; }
.toolbar .el-button { flex: 0 0 auto; }
.sku-match { display: grid; gap: 4px; margin-bottom: 6px; }
.sku-match .el-tag + .el-tag { margin-left: 5px; }
.el-pagination { margin-top: 16px; justify-content: flex-end; }
.dialog-heading span { display: block; color: #167d68; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.dialog-heading h2 { margin: 5px 0 0; color: #1f2937; font-size: 22px; }
.sample-form { padding: 0 8px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 18px; }
.form-span-2 { grid-column: 1 / -1; }
.sample-form :deep(.el-form-item) { margin-bottom: 14px; }
.sample-form :deep(.el-form-item__label) { padding-bottom: 5px; color: #374151; font-weight: 600; }
.sample-form :deep(.el-select), .sample-form :deep(.el-input), .sample-form :deep(.el-input-number) { width: 100%; }
.sku-editor { width: 100%; }
.sku-header, .sku-row { display: grid; grid-template-columns: 105px minmax(0, 1fr) 125px 42px; gap: 10px; align-items: center; }
.sku-header { margin-bottom: 6px; color: #84909c; font-size: 12px; }
.sku-row { margin-bottom: 8px; }
.sku-row .el-button { padding: 0; }
.price-note { margin-top: 12px; }
.blacklist-alert { margin-top: 8px; }
.detail-drawer { min-height: 100%; padding: 4px 2px 24px; }
.drawer-heading, .drawer-actions { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.drawer-heading { padding-bottom: 16px; border-bottom: 1px solid #eef0f3; }
.drawer-heading span { color: #167d68; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.drawer-heading h2 { margin: 5px 0; color: #1f2937; font-size: 22px; }
.detail-load-alert { margin: 14px 0; }
.drawer-actions { align-items: center; flex-wrap: wrap; padding: 14px 0; }
.detail-section { padding: 16px 0; border-top: 1px solid #eef0f3; }
.detail-section h3 { margin: 0 0 14px; color: #1f2937; font-size: 16px; }
.detail-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.detail-facts span { display: block; color: #84909c; font-size: 12px; }
.detail-facts b { display: block; margin-top: 4px; overflow-wrap: anywhere; color: #1f2937; font-size: 13px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
.detail-note { margin: 14px 0 0; color: #4b5563; white-space: pre-wrap; }
.video-list p { margin: 8px 0; color: #4b5563; font-size: 13px; }
.sku-detail-list p { margin: 6px 0; color: #374151; }
@media (max-width: 760px) {
  .sample-page .page-hero { align-items: stretch; flex-direction: column; gap: 16px; }
  .metrics { grid-template-columns: 1fr 1fr; }
  .toolbar { flex-wrap: wrap; overflow-x: visible; }
  .toolbar .el-input, .toolbar .el-select { flex: 1 1 100%; width: 100%; min-width: 100%; }
  .form-grid { grid-template-columns: 1fr; }
  .form-span-2 { grid-column: auto; }
  .sku-header, .sku-row { grid-template-columns: 1fr; gap: 5px; }
  .sku-header { display: none; }
  .detail-facts { grid-template-columns: 1fr; }
}
</style>
