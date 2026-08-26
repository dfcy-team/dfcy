<template>
  <section class="creator-page">
    <header class="page-hero">
      <div>
        <span>CREATOR OPERATIONS</span>
        <h1>建联任务</h1>
        <p>统一查看任务、进度、负责人和履约反馈。</p>
      </div>
    </header>

    <div class="metrics">
      <div><span>全部任务</span><strong>{{ displayValue(taskStats.total) }}</strong></div>
      <div><span>进行中</span><strong>{{ displayValue(taskStats.inProgress) }}</strong></div>
      <div><span>已建联</span><strong>{{ displayValue(taskStats.linked) }}</strong></div>
      <div><span>送样记录</span><strong>{{ displayValue(taskStats.fulfillments) }}</strong></div>
    </div>

    <el-card class="workspace-card" shadow="never">
      <div class="toolbar">
        <el-input
          v-model="filters.search"
          clearable
          placeholder="搜索任务/店铺/商品/负责人"
          @keyup.enter="applyFilters"
        />
        <el-select v-model="filters.status" clearable placeholder="全部状态" @change="applyFilters">
          <el-option v-for="(label, value) in OUTREACH_STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="filters.store" clearable filterable placeholder="全部店铺" @change="applyFilters">
          <el-option v-for="store in filterStoreOptions" :key="store.id" :label="store.name" :value="store.id" />
        </el-select>
        <el-select v-model="filters.dispatcher" clearable filterable placeholder="全部下发人" @change="applyFilters">
          <el-option v-for="dispatcher in dispatcherOptions" :key="dispatcher.id" :label="dispatcher.name" :value="dispatcher.id" />
        </el-select>
        <el-checkbox v-model="filters.normalOnly" @change="applyFilters">正常任务</el-checkbox>
        <el-checkbox v-model="filters.includeDeleted" @change="applyFilters">显示已删除</el-checkbox>
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button type="primary" :disabled="!canManage" @click="openCreate">新建任务</el-button>
      </div>

      <el-table
        v-loading="loading"
        :data="visibleRows"
        row-key="id"
        :row-class-name="rowClassName"
        empty-text="暂无建联任务"
        @row-click="openDetail"
      >
        <el-table-column label="任务" min-width="190">
          <template #default="{ row }">
            <b>{{ displayValue(row.task_no) }}</b>
            <small>{{ displayValue(row.task_name) }}</small>
          </template>
        </el-table-column>
        <el-table-column label="店铺 / 商品 ID" min-width="210">
          <template #default="{ row }">
            <b>{{ displayValue(row.store_name || row.store) }}</b>
            <small>商品 ID {{ displayValue(row.external_product_id) }}</small>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="100">
          <template #default="{ row }">
            <el-tag v-if="hasValue(row.priority)" :type="priorityTagType(row.priority)">
              {{ statusLabel(OUTREACH_PRIORITY_LABELS, row.priority) }}
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="目标进度" min-width="160">
          <template #default="{ row }">
            <el-progress v-if="hasValue(row.target_count)" :percentage="progress(row)" :format="() => progressLabel(row)" />
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="负责人" min-width="130">
          <template #default="{ row }">
            <b>{{ displayValue(row.owner_name || row.owner) }}</b>
            <small v-if="row.owner_name && hasValue(row.owner)">ID {{ row.owner }}</small>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="hasValue(row.status)">{{ statusLabel(OUTREACH_STATUS_LABELS, row.status) }}</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="任务下发人" min-width="130">
          <template #default="{ row }">{{ displayValue(row.dispatcher_name || row.dispatcher_id) }}</template>
        </el-table-column>
        <el-table-column label="任务履约反馈" min-width="180">
          <template #default="{ row }">{{ displayValue(row.notes) }}</template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间" min-width="165">
          <template #default="{ row }">{{ displayValue(row.started_at) }}</template>
        </el-table-column>
        <el-table-column prop="dispatch_time" label="下发时间" min-width="165">
          <template #default="{ row }">{{ displayValue(row.dispatch_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="205" fixed="right">
          <template #default="{ row }">
            <el-button link @click.stop="openDetail(row)">查看详情</el-button>
            <el-button v-if="!row.is_deleted" link :disabled="!canManage" @click.stop="openEdit(row)">修改</el-button>
            <el-button v-if="!row.is_deleted" link type="danger" :disabled="!canManage" @click.stop="removeTask(row)">删除</el-button>
            <el-button v-else link type="primary" :disabled="!canManage" @click.stop="restoreTask(row)">恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="visibleTotal"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="visibleTotal"
        layout="total, prev, pager, next"
        @current-change="load"
      />
    </el-card>

    <el-dialog
      v-model="createVisible"
      :title="editingTask ? '修改建联任务' : '新建建联任务'"
      width="620px"
      :close-on-click-modal="false"
      @closed="clearTaskDraft"
    >
      <el-form label-width="110px">
        <el-form-item v-if="editingTask" label="任务编号">
          <el-input :model-value="displayValue(editingTask.task_no)" readonly />
        </el-form-item>
        <el-form-item v-else label="任务编号">
          <el-input model-value="系统自动生成" readonly />
        </el-form-item>
        <el-form-item label="任务名称" required><el-input v-model="form.task_name" /></el-form-item>
        <el-form-item label="任务优先级" required>
          <el-select v-model="form.priority" placeholder="请选择优先级">
            <el-option v-for="(label, value) in OUTREACH_PRIORITY_LABELS" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="店铺" required>
          <el-select v-model="form.store" filterable placeholder="按店铺名称搜索" @change="selectMatchedStore">
            <el-option
              v-for="store in visibleStoreOptions"
              :key="store.id"
              :label="`${store.name}（${store.code || '—'} / ${store.country_code || '—'}）`"
              :value="store.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="商品 ID"><el-input v-model="form.external_product_id" @change="matchProduct" /></el-form-item>
        <el-form-item v-if="productMatchHint" label="匹配结果"><el-alert :closable="false" :type="productMatchType" :title="productMatchHint" /></el-form-item>
        <el-form-item label="SKU 前缀">
          <el-input v-model="form.sku_prefix" placeholder="匹配商品后自动填写，也可人工调整" />
        </el-form-item>
        <el-form-item label="目标人数" required><el-input-number v-model="form.target_count" :min="editingTask ? 0 : 1" :step="1" step-strictly /></el-form-item>
        <el-form-item label="负责人（BD）" required>
          <el-select v-model="form.owner" filterable placeholder="按姓名或账号搜索">
            <el-option v-for="user in bdOptions" :key="user.id" :label="`${user.full_name || user.username}（${user.username}）`" :value="user.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{ editingTask ? '保存修改' : '创建' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="targetsVisible" :title="`关联达人 · ${activeTask?.task_name || ''}`" width="820px" @closed="clearTargetDraft">
      <div class="target-bar">
        <el-select
          v-model="targetForm.influencer"
          filterable
          remote
          reserve-keyword
          clearable
          :remote-method="searchTargetInfluencers"
          :loading="targetLoading || targetInfluencerLoading"
          @change="resolveSelectedTargetInfluencer"
          placeholder="搜索达人名称/账号"
        >
          <el-option
            v-for="influencer in influencerOptions"
            :key="influencer.id"
            :label="influencerOptionLabel(influencer)"
            :value="influencer.id"
          />
        </el-select>
        <el-alert v-if="selectedTargetInfluencer?.is_blacklisted" class="blacklist-alert" type="error" :closable="false" title="该达人在黑名单中，不能关联。" />
        <el-input v-model="targetForm.notes" placeholder="备注（可选）" />
        <el-button type="primary" :disabled="!canManage || isTerminal(activeTask) || !selectedTargetInfluencer || targetInfluencerLoading || selectedTargetInfluencer?.is_blacklisted" @click="addTarget">添加关联达人</el-button>
      </div>
      <el-table v-loading="targetLoading" :data="displayTargets" empty-text="暂无关联达人">
        <el-table-column label="达人" min-width="220">
          <template #default="{ row }">
            <b>{{ targetDisplayName(row) }}</b>
            <small>{{ targetAccount(row) }}</small>
          </template>
        </el-table-column>
        <el-table-column label="建联结果" min-width="160">
          <template #default="{ row }">
            <el-select
              v-if="!row.is_deleted"
              v-model="row.outreach_result"
              :disabled="!canManage || isTerminal(activeTask) || isTargetTerminal(row)"
              @change="updateResult(row)"
            >
              <el-option v-for="(label, value) in OUTREACH_RESULT_LABELS" :key="value" :label="label" :value="value" />
            </el-select>
            <el-tag v-else>已删除</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="notes" label="备注" min-width="150" />
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="操作" min-width="145" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="!row.is_deleted"
              link
              type="primary"
              :disabled="!canCreateFulfillment || isTerminal(activeTask)"
              @click="openSampleFulfillment(row)"
            >创建送样</el-button>
            <el-button
              v-if="!row.is_deleted"
              link
              type="danger"
              :disabled="!canManage || isTerminal(activeTask) || isTargetTerminal(row)"
              @click="removeTarget(row)"
            >删除</el-button>
            <el-button v-else link type="primary" :disabled="!canManage || isTerminal(activeTask)" @click="restoreTarget(row)">恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-drawer v-model="detailVisible" direction="rtl" size="560px" :with-header="false" class="task-detail-drawer">
      <div class="drawer-body">
        <div class="drawer-head">
          <div>
            <span class="drawer-kicker">建联任务</span>
            <h2>{{ displayValue(detailTask?.task_name || detailTask?.task_no) }}</h2>
            <p>{{ displayValue(detailTask?.task_no) }} · ID {{ displayValue(detailTask?.id) }}</p>
          </div>
          <el-button circle text aria-label="关闭详情" @click="detailVisible = false">×</el-button>
        </div>

        <el-skeleton v-if="detailLoading" :rows="10" animated />
        <template v-else-if="detailTask">
          <el-alert v-if="detailError" class="drawer-alert" type="warning" :closable="false" :title="detailError" />
          <div class="drawer-actions">
            <el-button v-if="!detailTask.is_deleted" :disabled="!canManage" @click="openEdit(detailTask)">修改</el-button>
            <el-button v-if="!detailTask.is_deleted" type="danger" plain :disabled="!canManage" @click="removeTask(detailTask)">删除</el-button>
            <el-button v-if="detailTask.is_deleted" type="primary" :disabled="!canManage" @click="restoreTask(detailTask)">恢复任务</el-button>
            <el-button
              v-for="nextStatus in nextTaskStatuses(detailTask)"
              :key="nextStatus"
              link
              type="primary"
              :disabled="!canManage"
              @click="changeStatus(detailTask, nextStatus)"
            >{{ taskStatusActionLabel(nextStatus) }}</el-button>
          </div>

          <section class="detail-section">
            <div class="section-heading"><h3>任务事实</h3><el-tag>{{ statusLabel(OUTREACH_STATUS_LABELS, detailTask.status) }}</el-tag></div>
            <div class="detail-facts">
              <div><span>任务编号</span><b>{{ displayValue(detailTask.task_no) }}</b></div>
              <div><span>任务 ID</span><b>{{ displayValue(detailTask.id) }}</b></div>
              <div><span>任务名称</span><b>{{ displayValue(detailTask.task_name) }}</b></div>
              <div><span>店铺</span><b>{{ displayValue(detailTask.store_name || detailTask.store) }}</b></div>
              <div><span>商品</span><b>{{ displayValue(detailTask.product_name_snapshot) }}</b></div>
              <div><span>商品 ID</span><b>{{ displayValue(detailTask.external_product_id) }}</b></div>
              <div><span>SKU 前缀</span><b>{{ displayValue(detailTask.sku_prefix) }}</b></div>
              <div><span>优先级</span><b>{{ statusLabel(OUTREACH_PRIORITY_LABELS, detailTask.priority) }}</b></div>
              <div><span>目标进度</span><b>{{ detailProgressLabel }}</b></div>
              <div><span>负责人</span><b>{{ displayValue(detailTask.owner_name || detailTask.owner) }}</b></div>
              <div><span>任务下发人</span><b>{{ displayValue(detailTask.dispatcher_name || detailTask.dispatcher_id) }}</b></div>
              <div><span>开始时间</span><b>{{ formatTaskDateTime(detailTask.started_at) }}</b></div>
              <div><span>下发时间</span><b>{{ formatTaskDateTime(detailTask.dispatch_time) }}</b></div>
              <div><span>建联时间</span><b>{{ formatTaskDateTime(detailTask.outreach_at) }}</b></div>
              <div><span>完成时间</span><b>{{ formatTaskDateTime(detailTask.finalized_at) }}</b></div>
            </div>
            <div class="detail-validation">
              <b>送样完成校验</b>
              <span>{{ detailTask.sample_fulfillment_completed_count || 0 }} / {{ detailTask.target_count || 0 }}</span>
              <el-tag :type="detailTask.completion_validation?.target_reached ? 'success' : 'info'">{{ detailTask.completion_validation?.target_reached ? '已达到目标' : '未达到目标' }}</el-tag>
            </div>
            <div class="status-summary"><span v-for="(count, status) in (detailTask.sample_status_summary?.status_counts || detailTask.sample_fulfillment_status_summary || {})" :key="status">{{ statusLabel(FULFILLMENT_STATUS_LABELS, status) }} {{ count }}</span></div>
            <div class="detail-note"><span>任务履约反馈</span><p>{{ displayValue(detailTask.notes) }}</p></div>
          </section>

          <section class="detail-section">
            <div class="section-heading">
              <h3>送样信息</h3>
              <div class="section-heading-actions">
                <el-tag>{{ detailSamples.length }}</el-tag>
                <el-button
                  type="primary"
                  :disabled="!canCreateFulfillment || isTerminal(detailTask)"
                  @click="createSampleFromDetail"
                >创建送样</el-button>
              </div>
            </div>
            <div v-if="!canViewFulfillment" class="empty-state">当前账号无送样查看权限</div>
            <div v-else-if="detailSamples.length" class="sample-cards">
              <article v-for="sample in detailSamples" :key="sample.id" class="sample-card">
                <div><b>{{ displayValue(sample.fulfillment_no) }}</b><el-tag size="small">{{ statusLabel(FULFILLMENT_STATUS_LABELS, sample.status) }}</el-tag></div>
                <p>样品订单：{{ displayValue(sample.sample_order_no) }}</p>
                <p>达人：{{ displayValue(sample.influencer_name || sample.influencer) }}　成本：{{ displayAmount(sample.calculated_cost, sample) }}　视频匹配：{{ sample.video_match_count || 0 }}</p>
                <small>创建时间：{{ displayValue(sample.created_at) }}</small>
              </article>
            </div>
            <div v-else class="empty-state">暂无送样记录</div>
          </section>
        </template>
        <div v-else class="empty-state">任务详情不可用</div>
      </div>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import {
  addOutreachTarget,
  createOutreachTask,
  deleteOutreachTarget,
  deleteOutreachTask,
  fetchInfluencerResolve,
  fetchOutreachProgress,
  fetchOutreachTargets,
  fetchOutreachTask,
  fetchOutreachTaskOptions,
  fetchOutreachTasks,
  fetchSampleFulfillments,
  formatInfluencerError,
  FULFILLMENT_STATUS_LABELS,
  matchOutreachProduct,
  OUTREACH_PRIORITY_LABELS,
  OUTREACH_RESULT_LABELS,
  OUTREACH_STATUS_LABELS,
  restoreOutreachTarget,
  restoreOutreachTask,
  statusLabel,
  updateOutreachStatus,
  updateOutreachTarget,
  updateOutreachTask
} from '../../api/influencers';
import { applyProductCandidate } from './outreachProductMatch';
import { formatTaskDateTime } from './taskDateTime';
import { collectionRows, collectionTotal, detailData } from '../../utils/businessResponse';

const auth = useAuthStore();
const router = useRouter();
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const saving = ref(false);
const createVisible = ref(false);
const targetsVisible = ref(false);
const targetLoading = ref(false);
const targetInfluencerLoading = ref(false);
const activeTask = ref(null);
const targets = ref([]);
const deletedTargets = ref([]);
const detailVisible = ref(false);
const detailLoading = ref(false);
const detailTask = ref(null);
const detailProgress = ref(null);
const detailTargets = ref([]);
const detailSamples = ref([]);
const detailSampleTargetId = ref(null);
const detailError = ref('');
const editingTask = ref(null);
const storeOptions = ref([]);
const bdOptions = ref([]);
const influencerOptions = ref([]);
const taskOptionsLoaded = ref(false);
const filters = reactive({ search: '', status: '', store: null, dispatcher: null, normalOnly: false, includeDeleted: false });
const displayTargets = computed(() => [...targets.value, ...deletedTargets.value]);
const canManage = computed(() => auth.hasPermission('influencers.outreach.manage'));
const canCreateFulfillment = computed(() => auth.hasPermission('influencers.fulfillment.manage'));
const canViewFulfillment = computed(() => auth.hasPermission('influencers.fulfillment.view'));
const form = reactive({
  task_no: '',
  task_name: '',
  priority: 'normal',
  store: null,
  external_product_id: '',
  sku_prefix: '',
  target_count: 1,
  owner: null
});
const targetForm = reactive({ influencer: null, notes: '' });
const selectedTargetInfluencer = computed(() => influencerOptions.value.find((item) => String(item.id) === String(targetForm.influencer)) || null);
let targetInfluencerResolveSequence = 0;
let taskSubmitSequence = 0;
const matchedStoreIds = ref([]);
const matchedCandidates = ref([]);
const matchedSkuPrefixes = ref([]);
const productMatching = ref(false);
const productMatchHint = ref('');
const productMatchType = ref('info');
const productMatchSeq = ref(0);

const hasValue = (value) => value !== undefined && value !== null && value !== '';
const displayValue = (value) => hasValue(value) ? String(value) : '—';

function normalizeInfluencerAccount(value) {
  return String(value ?? '').trim().replace(/^@+/, '').trim().toLowerCase();
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

const filterStoreOptions = computed(() => {
  const optionsById = new Map(storeOptions.value.map((store) => [store.id, store]));
  rows.value.forEach((row) => {
    const id = row.store;
    if (hasValue(id) && !optionsById.has(id)) optionsById.set(id, { id, name: row.store_name || id });
  });
  return [...optionsById.values()];
});

const dispatcherOptions = computed(() => {
  const optionsById = new Map();
  rows.value.forEach((row) => {
    const id = row.dispatcher_id ?? row.dispatcher_name;
    if (hasValue(id) && !optionsById.has(id)) optionsById.set(id, {
      id,
      name: row.dispatcher_name || row.dispatcher_id
    });
  });
  return [...optionsById.values()];
});

const visibleStoreOptions = computed(() => {
  if (!matchedStoreIds.value.length) return storeOptions.value;
  const optionsById = new Map(storeOptions.value.map((store) => [store.id, store]));
  matchedCandidates.value.forEach((candidate) => optionsById.set(candidate.store_id, {
    id: candidate.store_id,
    name: candidate.store_name,
    code: candidate.store_code,
    country_code: candidate.country_code
  }));
  return matchedStoreIds.value.map((storeId) => optionsById.get(storeId)).filter(Boolean);
});

const isTerminal = (row) => ['completed', 'cancelled'].includes(row?.status);
const isTargetTerminal = (row) => ['success', 'rejected', 'no_response', 'blocked'].includes(row?.outreach_result);
const sampleProgressCount = (row) => Number(row?.sample_fulfillment_count ?? row?.fulfillment_count ?? row?.sample_count ?? 0);
const progress = (row) => row.target_count ? Math.min(100, Math.round(sampleProgressCount(row) * 100 / row.target_count)) : 0;
const progressLabel = (row) => `${displayValue(sampleProgressCount(row))}/${displayValue(row.target_count)}`;
const priorityTagType = (priority) => ({ urgent: 'danger', high: 'warning', low: 'info', normal: 'success' }[priority] || 'info');
const taskStatusTransitions = {
  pending: ['in_progress', 'cancelled'],
  in_progress: ['completed', 'cancelled'],
  completed: [],
  cancelled: []
};
const taskStatusActionLabel = (status) => ({ in_progress: '开始任务', completed: '完成任务', cancelled: '取消任务' }[status] || statusLabel(OUTREACH_STATUS_LABELS, status));
const nextTaskStatuses = (row) => taskStatusTransitions[row?.status] || [];
const rowClassName = () => 'clickable-task-row';

const visibleRows = computed(() => rows.value.filter((row) => {
  const dispatcher = row.dispatcher_id ?? row.dispatcher_name;
  const matchesDispatcher = !hasValue(filters.dispatcher) || String(dispatcher) === String(filters.dispatcher);
  const matchesNormal = !filters.normalOnly || row.priority === 'normal';
  return matchesDispatcher && matchesNormal;
}));
const visibleTotal = computed(() => filters.dispatcher || filters.normalOnly ? visibleRows.value.length : total.value);
const taskStats = computed(() => {
  const linkedValues = rows.value.map((row) => row.linked_count).filter(hasValue);
  const fulfillmentValues = rows.value
    .map((row) => row.sample_fulfillment_count ?? row.fulfillment_count ?? row.sample_count)
    .filter(hasValue);
  return {
    total: total.value,
    inProgress: rows.value.filter((row) => row.status === 'in_progress').length,
    linked: linkedValues.length ? linkedValues.reduce((sum, value) => sum + Number(value || 0), 0) : '—',
    fulfillments: fulfillmentValues.length ? fulfillmentValues.reduce((sum, value) => sum + Number(value || 0), 0) : '—'
  };
});
const detailProgressLabel = computed(() => {
  const row = detailProgress.value || detailTask.value || {};
  return `${displayValue(sampleProgressCount(row))}/${displayValue(row.target_count)}`;
});

async function load() {
  loading.value = true;
  const params = { page: page.value, page_size: pageSize.value };
  if (filters.search.trim()) params.search = filters.search.trim();
  if (filters.status) params.status = filters.status;
  if (filters.store) params.store = filters.store;
  if (filters.includeDeleted) params.include_deleted = 'true';
  const r = await fetchOutreachTasks(params);
  loading.value = false;
  if (r.success) {
    rows.value = collectionRows(r.data);
    total.value = collectionTotal(r.data);
  } else {
    ElMessage.error(formatInfluencerError(r, '任务加载失败'));
  }
}

function applyFilters() {
  page.value = 1;
  load();
}

function resetFilters() {
  Object.assign(filters, { search: '', status: '', store: null, dispatcher: null, normalOnly: false, includeDeleted: false });
  applyFilters();
}

function applyTaskOptions(data = {}) {
  storeOptions.value = data.stores || [];
  bdOptions.value = data.bd_users || [];
  influencerOptions.value = dedupeInfluencerCandidates(
    (data.influencers || []).filter((influencer) => influencer?.id !== undefined && influencer?.id !== null)
  );
}

async function loadTaskOptions(required = false) {
  if (taskOptionsLoaded.value) return true;
  const r = await fetchOutreachTaskOptions();
  if (!r.success) {
    if (required) ElMessage.error(formatInfluencerError(r, '店铺、BD 和达人选项加载失败'));
    return false;
  }
  applyTaskOptions(r.data);
  taskOptionsLoaded.value = true;
  return true;
}

function clearProductMatch() {
  matchedStoreIds.value = [];
  matchedCandidates.value = [];
  matchedSkuPrefixes.value = [];
  productMatchHint.value = '';
  productMatchType.value = 'info';
}

async function openCreate() {
  taskSubmitSequence += 1;
  saving.value = false;
  editingTask.value = null;
  Object.assign(form, {
    task_no: '',
    task_name: '',
    priority: 'normal',
    store: null,
    external_product_id: '',
    sku_prefix: '',
    target_count: 1,
    owner: null
  });
  clearProductMatch();
  if (!await loadTaskOptions(true)) return;
  createVisible.value = true;
}

async function openEdit(row) {
  if (!canManage.value || row.is_deleted) return;
  taskSubmitSequence += 1;
  saving.value = false;
  if (!await loadTaskOptions(true)) return;
  editingTask.value = { ...row };
  Object.assign(form, {
    task_no: row.task_no || '',
    task_name: row.task_name || '',
    priority: row.priority || 'normal',
    store: row.store ?? null,
    external_product_id: row.external_product_id || '',
    sku_prefix: row.sku_prefix || '',
    target_count: row.target_count ?? 0,
    owner: row.owner ?? null
  });
  clearProductMatch();
  createVisible.value = true;
}

function clearTaskDraft() {
  taskSubmitSequence += 1;
  saving.value = false;
  editingTask.value = null;
}

function selectMatchedStore(storeId) {
  const candidate = matchedCandidates.value.find((item) => item.store_id === storeId);
  matchedSkuPrefixes.value = applyProductCandidate(form, candidate);
}

async function matchProduct() {
  const productId = form.external_product_id.trim();
  const requestSeq = ++productMatchSeq.value;
  form.store = null;
  form.sku_prefix = '';
  matchedStoreIds.value = [];
  matchedCandidates.value = [];
  matchedSkuPrefixes.value = [];
  if (!productId) {
    productMatchHint.value = '';
    return;
  }
  productMatching.value = true;
  const r = await matchOutreachProduct(productId);
  if (requestSeq !== productMatchSeq.value || productId !== form.external_product_id.trim()) return;
  productMatching.value = false;
  if (!r.success) {
    productMatchType.value = 'error';
    productMatchHint.value = formatInfluencerError(r, '商品匹配失败');
    return;
  }
  const candidates = r.data?.candidates || [];
  matchedCandidates.value = candidates;
  matchedStoreIds.value = candidates.map((item) => item.store_id);
  if (!candidates.length) {
    productMatchType.value = 'warning';
    productMatchHint.value = '商品数据未导入，请手动选择店铺和填写 SKU 前缀';
    return;
  }
  if (r.data?.unique) {
    const candidate = candidates[0];
    form.store = candidate.store_id;
    selectMatchedStore(candidate.store_id);
    productMatchType.value = 'success';
    productMatchHint.value = `已匹配店铺：${candidate.store_name}${candidate.sku_prefixes?.length ? `，SKU 前缀：${candidate.sku_prefixes.join(',')}` : '，未找到 SKU 前缀'}`;
    return;
  }
  productMatchType.value = 'warning';
  productMatchHint.value = `匹配到 ${candidates.length}${r.data?.truncated ? '+' : ''} 家店铺，请选择正确店铺`;
}

async function submit() {
  if (editingTask.value) return submitEdit();
  if (!form.task_name || !form.store || !form.owner) return ElMessage.warning('请填写必填字段');
  const sequence = ++taskSubmitSequence;
  saving.value = true;
  const { task_no: ignoredTaskNo, ...payload } = form;
  const r = await createOutreachTask(payload);
  if (sequence !== taskSubmitSequence) return;
  saving.value = false;
  if (!r.success) return ElMessage.error(formatInfluencerError(r));
  createVisible.value = false;
  ElMessage.success('任务已创建');
  load();
}

async function submitEdit() {
  if (!form.task_name || !form.store || !form.owner) return ElMessage.warning('请填写必填字段');
  const sequence = ++taskSubmitSequence;
  const editedTask = { ...editingTask.value };
  saving.value = true;
  const payload = {
    task_name: form.task_name,
    priority: form.priority,
    store: form.store,
    external_product_id: form.external_product_id,
    sku_prefix: form.sku_prefix,
    target_count: form.target_count,
    owner: form.owner
  };
  const r = await updateOutreachTask(editedTask.id, payload, editedTask.version);
  if (sequence !== taskSubmitSequence) return;
  saving.value = false;
  if (!r.success) {
    ElMessage.error(formatInfluencerError(r));
    if (r.http_status === 409 || r.code === 'STATE_CONFLICT' || r.code === 'CONFLICT') await load();
    return;
  }
  const updated = detailData(r.data);
  if (detailTask.value?.id === editedTask.id) detailTask.value = { ...detailTask.value, ...updated };
  createVisible.value = false;
  ElMessage.success('任务已修改');
  await load();
  if (detailTask.value?.id === updated.id) await loadDetailData(detailTask.value, false);
}

async function changeStatus(row, status) {
  if (!nextTaskStatuses(row).includes(status)) return;
  if (status === 'cancelled') {
    try {
      await ElMessageBox.confirm('取消后不可恢复，确认取消该任务吗？', '确认取消', { type: 'warning' });
    } catch {
      return;
    }
  }
  const r = await updateOutreachStatus(row.id, status, row.version);
  if (!r.success) return ElMessage.error(formatInfluencerError(r));
  Object.assign(row, detailData(r.data));
  ElMessage.success('任务状态已更新');
  await load();
  if (detailTask.value?.id === row.id) {
    detailTask.value = { ...detailTask.value, ...row };
    await loadDetailData(detailTask.value, false);
  }
}

async function openDetail(row) {
  if (!row?.id) return;
  detailVisible.value = true;
  detailTask.value = { ...row };
  detailProgress.value = null;
  detailSamples.value = [];
  detailError.value = '';
  await loadDetailData(row);
}

async function loadDetailData(task, showLoading = true) {
  if (!task?.id) return;
  const taskId = task.id;
  if (showLoading) detailLoading.value = true;
  const sampleRequest = canViewFulfillment.value && task.task_no
    ? fetchSampleFulfillments({ search: task.task_no, page: 1, page_size: 100 })
    : Promise.resolve(null);
  const [taskResponse, progressResponse, sampleResponse] = await Promise.all([
    fetchOutreachTask(taskId, { include_deleted: task.is_deleted ? 'true' : undefined }),
    fetchOutreachProgress(taskId),
    sampleRequest
  ]);
  if (detailTask.value?.id !== taskId) return;
  const failures = [];
  if (taskResponse?.success) detailTask.value = { ...detailTask.value, ...detailData(taskResponse.data) };
  else failures.push('任务事实加载失败');
  if (progressResponse?.success) detailProgress.value = detailData(progressResponse.data);
  else failures.push('进度加载失败');
  if (sampleResponse?.success) {
    detailSamples.value = collectionRows(sampleResponse.data).filter((sample) => String(sample.outreach_task) === String(taskId));
  } else if (canViewFulfillment.value) {
    failures.push('送样信息加载失败');
  }
  detailError.value = failures.join('；');
  detailLoading.value = false;
}

async function removeTask(row) {
  if (!canManage.value || !row?.id || row.is_deleted) return;
  try {
    await ElMessageBox.confirm(`确认删除任务“${displayValue(row.task_no)}”吗？删除将保留后端软删除记录。`, '确认删除', { type: 'warning' });
  } catch {
    return;
  }
  const r = await deleteOutreachTask(row.id, row.version);
  if (!r.success) return ElMessage.error(formatInfluencerError(r));
  ElMessage.success('任务已删除');
  if (detailTask.value?.id === row.id) {
    detailVisible.value = false;
    detailTask.value = null;
  }
  await load();
}

async function restoreTask(row) {
  if (!canManage.value || !row?.id || !row.is_deleted) return;
  const r = await restoreOutreachTask(row.id, row.version);
  if (!r.success) return ElMessage.error(formatInfluencerError(r));
  ElMessage.success('任务已恢复');
  await load();
}

async function openTargets(row) {
  targetInfluencerResolveSequence += 1;
  targetInfluencerLoading.value = false;
  activeTask.value = row;
  targetsVisible.value = true;
  deletedTargets.value = [];
  Object.assign(targetForm, { influencer: null, notes: '' });
  await loadTaskOptions();
  await loadTargets();
}

function clearTargetDraft() {
  targetInfluencerResolveSequence += 1;
  targetInfluencerLoading.value = false;
  Object.assign(targetForm, { influencer: null, notes: '' });
}

async function loadTargets() {
  if (!activeTask.value?.id) return;
  targetLoading.value = true;
  const r = await fetchOutreachTargets(activeTask.value.id, { page: 1, page_size: 100 });
  targetLoading.value = false;
  targets.value = r.success ? collectionRows(r.data) : [];
  if (!r.success) ElMessage.error(formatInfluencerError(r));
  if (detailTask.value?.id === activeTask.value.id && r.success) detailTargets.value = [...targets.value];
}

async function refreshActiveTask() {
  const activeId = activeTask.value?.id || detailTask.value?.id;
  await load();
  const fresh = rows.value.find((item) => item.id === activeId);
  if (activeTask.value?.id === activeId && fresh) activeTask.value = fresh;
  if (detailTask.value?.id === activeId) {
    detailTask.value = { ...detailTask.value, ...(fresh || {}) };
    await loadDetailData(detailTask.value, false);
  }
}

function influencerOptionLabel(influencer) {
  const primary = influencer.name || influencer.code || `达人 ${influencer.id}`;
  const account = [influencer.platform, influencer.handle].filter(Boolean).join(' · ');
  return account ? `${primary}（${account}）` : primary;
}

function targetDisplayName(row) {
  return row.influencer_name || row.influencer_code || (row.influencer ? `达人 ${row.influencer}` : '—');
}

function targetAccount(row) {
  const account = [row.influencer_platform, row.influencer_code].filter(Boolean).join(' · ');
  return account || (row.influencer ? `ID ${row.influencer}` : '—');
}

function displayAmount(value, row) {
  if (!hasValue(value)) return '—';
  const currency = row?.items?.find((item) => item.currency)?.currency;
  return currency ? `${value} ${currency}` : String(value);
}

function openSampleFulfillment(row) {
  if (!activeTask.value || !row?.id || !canCreateFulfillment.value || isTerminal(activeTask.value)) return;
  router.push({
    path: '/influencers/sample-fulfillments',
    query: {
      outreach_task: String(activeTask.value.id)
    }
  });
}

function createSampleFromDetail() {
  const task = detailTask.value;
  if (!task || !canCreateFulfillment.value || isTerminal(task)) return;
  router.push({
    path: '/influencers/sample-fulfillments',
    query: {
      outreach_task: String(task.id)
    }
  });
}

async function addTarget() {
  if (targetInfluencerLoading.value) return ElMessage.warning('达人账号仍在校验，请稍候');
  if (!targetForm.influencer || !selectedTargetInfluencer.value) return ElMessage.warning('请从搜索结果中选择达人');
  if (selectedTargetInfluencer.value?.is_blacklisted) return ElMessage.error('该达人在黑名单中，不能关联');
  const r = await addOutreachTarget(activeTask.value.id, targetForm.influencer, undefined, targetForm.notes);
  if (!r.success) return ElMessage.error(formatInfluencerError(r));
  Object.assign(targetForm, { influencer: null, notes: '' });
  ElMessage.success('达人已关联');
  await loadTargets();
  await refreshActiveTask();
}

async function searchTargetInfluencers(search) {
  const sequence = ++targetInfluencerResolveSequence;
  targetInfluencerLoading.value = true;
  const response = await fetchInfluencerResolve(String(search || '').trim());
  if (sequence !== targetInfluencerResolveSequence) return;
  targetInfluencerLoading.value = false;
  if (!response.success) return ElMessage.error(formatInfluencerError(response, '达人账号搜索失败'));
  influencerOptions.value = responseInfluencerCandidates(response);
}

async function resolveSelectedTargetInfluencer(id) {
  const sequence = ++targetInfluencerResolveSequence;
  const selected = influencerOptions.value.find((item) => String(item.id) === String(id));
  if (!selected) {
    targetInfluencerLoading.value = false;
    return;
  }
  targetInfluencerLoading.value = true;
  const response = await fetchInfluencerResolve(selected.handle || selected.code || selected.name);
  if (sequence !== targetInfluencerResolveSequence) return;
  targetInfluencerLoading.value = false;
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
    targetForm.influencer = preferred?.id ?? resolved.id;
  }
}

async function updateResult(row) {
  const r = await updateOutreachTarget(activeTask.value.id, row.id, { outreach_result: row.outreach_result }, row.version);
  if (!r.success) {
    ElMessage.error(formatInfluencerError(r));
    return loadTargets();
  }
  Object.assign(row, detailData(r.data));
  await refreshActiveTask();
}

async function removeTarget(row) {
  const r = await deleteOutreachTarget(activeTask.value.id, row.id, row.version);
  if (!r.success) return ElMessage.error(formatInfluencerError(r));
  const deleted = { ...row, ...detailData(r.data), is_deleted: true };
  deletedTargets.value.push(deleted);
  targets.value = targets.value.filter((item) => item.id !== row.id);
  ElMessage.success('关联达人已删除');
  await refreshActiveTask();
}

async function restoreTarget(row) {
  const r = await restoreOutreachTarget(activeTask.value.id, row, row.version);
  if (!r.success) return ElMessage.error(formatInfluencerError(r));
  deletedTargets.value = deletedTargets.value.filter((item) => item.id !== row.id);
  targets.value.push(detailData(r.data));
  ElMessage.success('关联达人已恢复');
  await refreshActiveTask();
}

onMounted(async () => {
  await load();
  await loadTaskOptions();
});
</script>

<style scoped>
.creator-page { display: grid; gap: 18px; }
.creator-page .page-hero { display: flex; justify-content: space-between; align-items: end; padding: 24px; border-radius: 16px; background: linear-gradient(120deg, #0b5345, #167d68); color: #fff; }
.page-hero h1 { margin: 6px 0; }
.page-hero p { margin: 0; opacity: .82; }
.creator-page small, .target-card small, .sample-card small { display: block; color: #84909c; font-size: 12px; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; overflow: hidden; }
.metrics div { padding: 15px 18px; border-right: 1px solid #e5e7eb; }
.metrics div:last-child { border: 0; }
.metrics span, .metrics strong { display: block; }
.metrics span { color: #84909c; font-size: 12px; }
.metrics strong { margin-top: 5px; color: #1f2937; font-size: 24px; }
.toolbar { display: flex; flex-wrap: nowrap; align-items: center; gap: 10px; margin-bottom: 16px; overflow-x: auto; }
.toolbar .el-input { flex: 1 1 420px; min-width: 280px; }
.toolbar .el-select { flex: 0 0 140px; width: 140px; }
.toolbar .el-checkbox, .toolbar .el-button { flex: 0 0 auto; }
.target-bar { display: flex; gap: 10px; margin-bottom: 14px; }
.target-bar .el-input, .target-bar .el-select { max-width: 320px; flex: 1; }
.el-pagination { margin-top: 16px; justify-content: flex-end; }
.clickable-task-row { cursor: pointer; }
.drawer-body { min-height: 100%; padding: 4px 2px 22px; }
.drawer-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; padding-bottom: 18px; border-bottom: 1px solid #eef0f3; }
.drawer-kicker { color: #167d68; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.drawer-head h2 { margin: 6px 0 4px; color: #1f2937; font-size: 22px; }
.drawer-head p { margin: 0; color: #84909c; font-size: 12px; }
.drawer-alert { margin-top: 16px; }
.drawer-actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 16px 0; border-bottom: 1px solid #eef0f3; }
.detail-section { padding: 18px 0; border-bottom: 1px solid #eef0f3; }
.section-heading { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; }
.section-heading h3 { margin: 0; color: #1f2937; font-size: 16px; }
.section-heading-actions { display: flex; align-items: center; gap: 8px; }
.detail-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; }
.detail-facts div, .detail-note { min-width: 0; }
.detail-facts span, .detail-note > span { display: block; margin-bottom: 4px; color: #84909c; font-size: 12px; }
.detail-facts b { display: block; overflow-wrap: anywhere; color: #1f2937; font-size: 13px; font-weight: 600; }
.detail-note { margin-top: 15px; padding-top: 14px; border-top: 1px dashed #e5e7eb; }
.detail-note p { margin: 0; color: #374151; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.detail-validation { display: flex; align-items: center; gap: 10px; margin-top: 16px; padding: 12px; border-radius: 8px; background: #f5faf7; color: #374151; }
.status-summary { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; color: #84909c; font-size: 12px; }
.status-summary span { padding: 4px 7px; border: 1px solid #e5e7eb; border-radius: 999px; background: #fff; }
.blacklist-alert { margin-bottom: 10px; }
.target-cards, .sample-cards { display: grid; gap: 10px; }
.target-card, .sample-card { padding: 12px; border: 1px solid #e5e7eb; border-radius: 10px; background: #fafcfb; }
.target-card > div { display: flex; justify-content: space-between; gap: 8px; }
.target-card p, .sample-card p { margin: 8px 0 0; color: #4b5563; font-size: 12px; }
.target-card .el-button { margin-top: 7px; padding-left: 0; }
.sample-card > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.sample-create-row { display: flex; gap: 8px; margin-bottom: 12px; }
.sample-create-row .el-select { flex: 1; }
.empty-state { padding: 16px 0; color: #84909c; font-size: 13px; text-align: center; }
@media (max-width: 800px) {
  .creator-page .page-hero, .target-bar { align-items: stretch; flex-direction: column; }
  .metrics { grid-template-columns: 1fr 1fr; }
  .toolbar { flex-wrap: wrap; overflow-x: visible; }
  .toolbar .el-input, .toolbar .el-select { flex: 1 1 100%; width: 100%; min-width: 100%; }
  .target-bar .el-input, .target-bar .el-select { max-width: none; }
  .detail-facts { grid-template-columns: 1fr; }
  .sample-create-row { flex-direction: column; }
}
</style>
