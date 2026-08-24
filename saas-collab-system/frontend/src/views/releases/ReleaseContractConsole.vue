<template>
  <AppPage
    eyebrow="RELEASE GOVERNANCE"
    title="发布合同操作台"
    subtitle="统一查看发布候选、门禁证据、独立审批、构建产物和发布状态。"
    boundary-note="操作台只记录受控发布事实和外部平台执行结果，不直接上传代码、不调用微信发布接口，也不绕过人工审批。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="canManage" type="primary" @click="openCreate">新建发布合同</el-button>
    </template>

    <section class="summary-grid" aria-label="发布合同概览">
      <article class="summary-card">
        <span>当前范围</span>
        <strong>{{ total }}</strong>
        <small>份发布合同</small>
      </article>
      <article class="summary-card summary-card--warning">
        <span>待处理</span>
        <strong>{{ pendingCount }}</strong>
        <small>草稿 / 审批 / 发布中</small>
      </article>
      <article class="summary-card summary-card--success">
        <span>已完成</span>
        <strong>{{ completedCount }}</strong>
        <small>完成或已回滚</small>
      </article>
      <article class="summary-card summary-card--info">
        <span>门禁健康</span>
        <strong>{{ healthyGateCount }}</strong>
        <small>全部门禁有效</small>
      </article>
    </section>

    <section class="filter-bar">
      <el-select v-model="filters.environment" clearable placeholder="全部环境" aria-label="环境筛选">
        <el-option label="测试" value="test" />
        <el-option label="预览" value="preview" />
        <el-option label="生产" value="production" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" aria-label="状态筛选">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-button type="primary" plain @click="load">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <span class="filter-bar__hint">点击合同编号查看完整证据链</span>
    </section>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />

    <el-table v-else :data="rows" border stripe class="contract-table">
      <el-table-column label="合同编号" min-width="190" fixed="left">
        <template #default="{ row }">
          <el-button link type="primary" class="contract-link" @click="openDetail(row)">
            {{ row.contract_no }}
          </el-button>
          <small class="commit">{{ shortCommit(row.commit_sha) }}</small>
        </template>
      </el-table-column>
      <el-table-column prop="application_code" label="应用" min-width="145" />
      <el-table-column label="环境" width="88">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ environmentLabel(row.environment) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="风险" width="88">
        <template #default="{ row }">
          <el-tag size="small" :type="riskType(row.risk_level)">{{ riskLabel(row.risk_level) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="126">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="发布门禁" min-width="150">
        <template #default="{ row }">
          <div class="gate-cell">
            <el-progress
              :percentage="gatePercentage(row)"
              :status="gatePercentage(row) === 100 ? 'success' : undefined"
              :stroke-width="7"
            />
            <span>{{ row.gate_summary?.passed || 0 }}/{{ row.gate_summary?.required || 6 }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="72" align="center" />
      <el-table-column label="更新时间" min-width="165">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" min-width="250" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button
            v-if="canManage && row.status === 'draft'"
            size="small"
            type="primary"
            plain
            @click="openGate(row)"
          >
            录入门禁
          </el-button>
          <el-button
            v-if="canManage && row.status === 'draft' && gatePercentage(row) === 100"
            size="small"
            type="primary"
            @click="runAction(row, 'submit-review')"
          >
            提交审批
          </el-button>
          <el-button
            v-if="canApprove && row.status === 'review_pending'"
            size="small"
            type="success"
            @click="openApproval(row)"
          >
            审批
          </el-button>
          <el-button
            v-if="canApprove && row.status === 'rollback_required'"
            size="small"
            type="warning"
            @click="openApproval(row)"
          >
            回滚审批
          </el-button>
          <el-button
            v-if="canExecute && row.status === 'approved'"
            size="small"
            type="primary"
            @click="openBuild(row)"
          >
            确认构建
          </el-button>
          <el-dropdown
            v-if="canExecute && transitionActions(row).length"
            trigger="click"
            @command="(command) => runTransitionCommand(row, command)"
          >
            <el-button size="small">状态推进⌄</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="action in transitionActions(row)"
                  :key="action.command"
                  :command="action.command"
                >
                  {{ action.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="detailOpen" title="发布合同证据链" size="min(760px, 96vw)">
      <template v-if="selected">
        <div class="drawer-heading">
          <div>
            <small>{{ selected.application_code }} · {{ environmentLabel(selected.environment) }}</small>
            <h2>{{ selected.contract_no }}</h2>
          </div>
          <el-tag :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag>
        </div>

        <el-descriptions :column="2" border class="detail-block">
          <el-descriptions-item label="候选提交">{{ selected.commit_sha }}</el-descriptions-item>
          <el-descriptions-item label="API 合同">{{ selected.api_contract_version }}</el-descriptions-item>
          <el-descriptions-item label="风险等级">{{ riskLabel(selected.risk_level) }}</el-descriptions-item>
          <el-descriptions-item label="合同版本">v{{ selected.version }}</el-descriptions-item>
          <el-descriptions-item label="回滚版本">{{ selected.rollback_version }}</el-descriptions-item>
          <el-descriptions-item label="观察窗口">{{ selected.observation_minutes }} 分钟</el-descriptions-item>
          <el-descriptions-item label="发布范围" :span="2">
            <el-tag v-for="item in selected.scope || []" :key="item" size="small" effect="plain">{{ item }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="回滚点" :span="2">{{ selected.rollback_point }}</el-descriptions-item>
        </el-descriptions>

        <h3>门禁证据</h3>
        <div class="evidence-list">
          <article v-for="gate in selected.gate_results || []" :key="gate.code" class="evidence-row">
            <div>
              <strong>{{ gateLabel(gate.code) }}</strong>
              <small>{{ gate.evidence_ref }}</small>
            </div>
            <el-tag size="small" :type="gate.status === 'passed' ? 'success' : 'danger'">
              {{ gate.status === 'passed' ? '通过' : '未通过' }}
            </el-tag>
          </article>
          <el-empty v-if="!selected.gate_results?.length" description="尚未录入门禁证据" />
        </div>

        <h3>独立审批</h3>
        <div class="approval-grid">
          <article v-for="type in approvalTypes" :key="type.value" class="approval-card">
            <span>{{ type.label }}</span>
            <strong>{{ approvalDecision(type.value) }}</strong>
            <small>{{ approvalReason(type.value) }}</small>
          </article>
        </div>

        <template v-if="selected.artifact">
          <h3>不可变构建产物</h3>
          <el-descriptions :column="1" border class="detail-block">
            <el-descriptions-item label="构建编号">{{ selected.artifact.build_no }}</el-descriptions-item>
            <el-descriptions-item label="产物哈希"><code>{{ selected.artifact.artifact_hash }}</code></el-descriptions-item>
            <el-descriptions-item label="配置版本">{{ selected.artifact.config_version }}</el-descriptions-item>
          </el-descriptions>
        </template>

        <template v-if="selected.audit_events?.length">
          <h3>审计时间线</h3>
          <el-timeline>
            <el-timeline-item
              v-for="event in selected.audit_events"
              :key="`${event.action}-${event.created_at}`"
              :timestamp="formatTime(event.created_at)"
            >
              {{ event.action }}：{{ event.from_status }} → {{ event.to_status }}
            </el-timeline-item>
          </el-timeline>
        </template>
      </template>
    </el-drawer>

    <el-dialog v-model="createOpen" title="新建发布合同" width="min(680px, 94vw)">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="应用编码"><el-input v-model="createForm.application_code" /></el-form-item>
          <el-form-item label="目标环境">
            <el-select v-model="createForm.environment">
              <el-option label="测试" value="test" />
              <el-option label="预览" value="preview" />
              <el-option label="生产" value="production" />
            </el-select>
          </el-form-item>
          <el-form-item label="候选 Commit SHA" class="form-span-2">
            <el-input v-model="createForm.commit_sha" maxlength="64" />
          </el-form-item>
          <el-form-item label="API 合同版本"><el-input v-model="createForm.api_contract_version" /></el-form-item>
          <el-form-item label="风险等级">
            <el-select v-model="createForm.risk_level">
              <el-option label="低" value="low" />
              <el-option label="中" value="medium" />
              <el-option label="高" value="high" />
              <el-option label="关键" value="critical" />
            </el-select>
          </el-form-item>
          <el-form-item label="发布范围（每行一项）" class="form-span-2">
            <el-input v-model="createForm.scope_text" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="回滚版本"><el-input v-model="createForm.rollback_version" /></el-form-item>
          <el-form-item label="观察窗口（分钟）">
            <el-input-number v-model="createForm.observation_minutes" :min="5" :max="1440" />
          </el-form-item>
          <el-form-item label="回滚点" class="form-span-2">
            <el-input v-model="createForm.rollback_point" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">创建草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="gateOpen" title="录入发布门禁证据" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="门禁项">
          <el-select v-model="gateForm.code">
            <el-option v-for="gate in gateOptions" :key="gate.value" :label="gate.label" :value="gate.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="结果">
          <el-radio-group v-model="gateForm.status">
            <el-radio value="passed">通过</el-radio>
            <el-radio value="failed">未通过</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="证据引用">
          <el-input v-model="gateForm.evidence_ref" placeholder="例如：ci://run/1234（不要填写密钥）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="gateOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitGate">保存证据</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="approvalOpen" title="独立审批决策" width="min(540px, 94vw)">
      <el-alert
        title="创建人不能审批；同一人员不能承担多个审批角色。最终以服务端职责分离校验为准。"
        type="warning"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="dialog-form">
        <el-form-item label="审批角色">
          <el-select v-model="approvalForm.approval_type">
            <el-option v-for="type in approvalTypes" :key="type.value" :label="type.label" :value="type.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="决策">
          <el-radio-group v-model="approvalForm.decision">
            <el-radio value="approved">批准</el-radio>
            <el-radio value="rejected">拒绝</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="审批意见"><el-input v-model="approvalForm.reason" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="approvalOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitApproval">提交决策</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="buildOpen" title="确认不可变构建产物" width="min(620px, 94vw)">
      <el-alert
        title="构建 Commit 必须与发布合同冻结的候选提交完全一致。产物哈希提交后不可修改。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="dialog-form">
        <el-form-item label="构建编号"><el-input v-model="buildForm.build_no" /></el-form-item>
        <el-form-item label="Commit SHA"><el-input v-model="buildForm.commit_sha" /></el-form-item>
        <el-form-item label="SHA-256 产物哈希"><el-input v-model="buildForm.artifact_hash" maxlength="64" /></el-form-item>
        <el-form-item label="配置版本"><el-input v-model="buildForm.config_version" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="buildOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitBuild">确认构建</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import {
  confirmReleaseBuild,
  createReleaseContract,
  decideReleaseApproval,
  fetchReleaseContract,
  fetchReleaseContracts,
  recordReleaseGate,
  runReleaseAction
} from '../../api/releaseContracts';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('release.contract.manage'));
const canApprove = computed(() => auth.hasPermission('release.contract.approve'));
const canExecute = computed(() => auth.hasPermission('release.contract.execute'));
const state = ref('loading');
const capability = ref('pending');
const errorMessage = ref('');
const rows = ref([]);
const total = ref(0);
const selected = ref(null);
const detailOpen = ref(false);
const createOpen = ref(false);
const gateOpen = ref(false);
const approvalOpen = ref(false);
const buildOpen = ref(false);
const submitting = ref(false);
const activeContract = ref(null);
const filters = reactive({ environment: '', status: '' });

const statusOptions = [
  ['draft', '草稿'], ['review_pending', '待审批'], ['approved', '已批准'],
  ['built', '已构建'], ['uploaded', '已上传'], ['platform_review', '平台审核中'],
  ['scheduled', '已排期'], ['releasing', '发布中'], ['released', '已发布'],
  ['observing', '观察中'], ['completed', '已完成'], ['rollback_required', '待回滚'],
  ['rolled_back', '已回滚'], ['release_failed', '发布失败'], ['cancelled', '已取消']
].map(([value, label]) => ({ value, label }));

const gateOptions = [
  ['engineering-quality', '工程质量'],
  ['miniapp-special', '小程序专项'],
  ['backend-compatibility', '后端兼容性'],
  ['end-to-end', '端到端验证'],
  ['release-readiness', '发布就绪'],
  ['evidence-integrity', '证据完整性']
].map(([value, label]) => ({ value, label }));
const approvalTypes = [
  { value: 'business', label: '业务审批' },
  { value: 'technical', label: '技术审批' },
  { value: 'security', label: '安全审批' },
  { value: 'rollback', label: '回滚审批' }
];

const createForm = reactive({
  application_code: 'saas-miniapp',
  environment: 'test',
  commit_sha: '',
  api_contract_version: 'miniapp-v1',
  scope_text: '小程序登录联调\n发布合同工作台',
  risk_level: 'medium',
  rollback_version: '',
  rollback_point: '',
  observation_minutes: 30
});
const gateForm = reactive({
  code: 'engineering-quality',
  category: 'release-readiness',
  status: 'passed',
  evidence_ref: ''
});
const approvalForm = reactive({
  approval_type: 'business',
  decision: 'approved',
  reason: ''
});
const buildForm = reactive({
  build_no: '',
  commit_sha: '',
  artifact_hash: '',
  config_version: ''
});

const completedCount = computed(() =>
  rows.value.filter((row) => ['completed', 'rolled_back'].includes(row.status)).length
);
const pendingCount = computed(() =>
  rows.value.filter((row) => !['completed', 'rolled_back', 'cancelled'].includes(row.status)).length
);
const healthyGateCount = computed(() =>
  rows.value.filter((row) => gatePercentage(row) === 100).length
);

const statusLabel = (value) => statusOptions.find((item) => item.value === value)?.label || value;
const statusType = (value) => {
  if (['completed', 'released', 'approved', 'rolled_back'].includes(value)) return 'success';
  if (['review_pending', 'scheduled', 'observing', 'platform_review'].includes(value)) return 'warning';
  if (['release_failed', 'review_failed', 'rollback_required', 'rejected'].includes(value)) return 'danger';
  return 'info';
};
const environmentLabel = (value) => ({ test: '测试', preview: '预览', production: '生产' }[value] || value);
const riskLabel = (value) => ({ low: '低', medium: '中', high: '高', critical: '关键' }[value] || value);
const riskType = (value) => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[value] || 'info');
const gateLabel = (value) => gateOptions.find((item) => item.value === value)?.label || value;
const shortCommit = (value = '') => (value.length > 12 ? `${value.slice(0, 12)}…` : value);
const formatTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
const gatePercentage = (row) => {
  const required = Number(row.gate_summary?.required || 6);
  return Math.round((Number(row.gate_summary?.passed || 0) / required) * 100);
};

function approvalFor(type) {
  return selected.value?.approvals?.find((item) => item.approval_type === type);
}
function approvalDecision(type) {
  const decision = approvalFor(type)?.decision;
  return decision === 'approved' ? '已批准' : decision === 'rejected' ? '已拒绝' : '待审批';
}
function approvalReason(type) {
  return approvalFor(type)?.reason || '尚无审批记录';
}

async function load() {
  state.value = 'loading';
  errorMessage.value = '';
  const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
  const response = await fetchReleaseContracts(params);
  if (!response.success) {
    state.value = statusFromApiResponse(response, navigator.onLine);
    errorMessage.value = response.message;
    return;
  }
  rows.value = response.data.results || [];
  total.value = response.data.count || rows.value.length;
  capability.value = response.data.api_status || 'connected';
  state.value = rows.value.length ? 'ready' : 'empty';
}

function resetFilters() {
  filters.environment = '';
  filters.status = '';
  load();
}

async function openDetail(row) {
  detailOpen.value = true;
  selected.value = { ...row, gate_results: [], approvals: [], audit_events: [] };
  const response = await fetchReleaseContract(row.id);
  if (response.success) {
    selected.value = response.data;
    capability.value = response.data.api_status || capability.value;
  } else {
    ElMessage.error(response.message);
    detailOpen.value = false;
  }
}

function openCreate() {
  createOpen.value = true;
}

function openGate(row) {
  activeContract.value = row;
  const missing = row.gate_summary?.missing?.[0];
  gateForm.code = missing || 'engineering-quality';
  gateForm.status = 'passed';
  gateForm.evidence_ref = '';
  gateOpen.value = true;
}

function openApproval(row) {
  activeContract.value = row;
  if (row.status === 'rollback_required') {
    approvalForm.approval_type = 'rollback';
    approvalForm.decision = 'approved';
    approvalForm.reason = '';
    approvalOpen.value = true;
    return;
  }
  const decided = new Set((row.approvals || []).map((item) => item.approval_type));
  approvalForm.approval_type = ['business', 'technical', 'security'].find((item) => !decided.has(item)) || 'business';
  approvalForm.decision = 'approved';
  approvalForm.reason = '';
  approvalOpen.value = true;
}

function openBuild(row) {
  activeContract.value = row;
  buildForm.build_no = `build-${Date.now()}`;
  buildForm.commit_sha = row.commit_sha;
  buildForm.artifact_hash = '';
  buildForm.config_version = '';
  buildOpen.value = true;
}

async function submitCreate() {
  if (!createForm.commit_sha || !createForm.rollback_version || !createForm.rollback_point) {
    ElMessage.warning('请填写候选提交、回滚版本和回滚点。');
    return;
  }
  submitting.value = true;
  const response = await createReleaseContract({
    application_code: createForm.application_code,
    environment: createForm.environment,
    commit_sha: createForm.commit_sha.trim(),
    api_contract_version: createForm.api_contract_version,
    scope: createForm.scope_text.split('\n').map((item) => item.trim()).filter(Boolean),
    risk_level: createForm.risk_level,
    rollback_version: createForm.rollback_version,
    rollback_point: createForm.rollback_point,
    stop_conditions: [{ metric: 'error_rate', operator: '>', threshold: 0.05 }],
    observation_minutes: createForm.observation_minutes
  });
  submitting.value = false;
  finishMutation(response, '发布合同草稿已创建', () => { createOpen.value = false; });
}

async function submitGate() {
  if (!gateForm.evidence_ref.trim()) {
    ElMessage.warning('请填写可追溯的证据引用。');
    return;
  }
  const row = activeContract.value;
  submitting.value = true;
  const evaluatedAt = new Date();
  const response = await recordReleaseGate(row.id, {
    version: row.version,
    code: gateForm.code,
    category: gateForm.category,
    status: gateForm.status,
    evidence_ref: gateForm.evidence_ref.trim(),
    evaluated_at: evaluatedAt.toISOString(),
    expires_at: new Date(evaluatedAt.getTime() + 24 * 60 * 60 * 1000).toISOString()
  });
  submitting.value = false;
  finishMutation(response, '门禁证据已记录', () => { gateOpen.value = false; });
}

async function submitApproval() {
  if (approvalForm.reason.trim().length < 3) {
    ElMessage.warning('审批意见至少需要 3 个字符。');
    return;
  }
  const row = activeContract.value;
  submitting.value = true;
  const response = await decideReleaseApproval(row.id, {
    version: row.version,
    approval_type: approvalForm.approval_type,
    decision: approvalForm.decision,
    reason: approvalForm.reason.trim()
  });
  submitting.value = false;
  finishMutation(response, '审批决策已记录', () => { approvalOpen.value = false; });
}

async function submitBuild() {
  if (!/^[a-fA-F0-9]{64}$/.test(buildForm.artifact_hash)) {
    ElMessage.warning('产物哈希必须是 64 位 SHA-256 十六进制字符串。');
    return;
  }
  const row = activeContract.value;
  submitting.value = true;
  const response = await confirmReleaseBuild(row.id, {
    version: row.version,
    build_no: buildForm.build_no,
    commit_sha: buildForm.commit_sha,
    artifact_hash: buildForm.artifact_hash.toLowerCase(),
    config_version: buildForm.config_version,
    manifest: { source: 'release-contract-console' },
    reason: '在内部操作台确认不可变构建产物'
  });
  submitting.value = false;
  finishMutation(response, '构建产物已冻结', () => { buildOpen.value = false; });
}

async function runAction(row, action, extra = {}) {
  const response = await runReleaseAction(row.id, action, {
    version: row.version,
    reason: `通过内部发布合同操作台记录：${action}`,
    evidence_refs: [],
    ...extra
  });
  finishMutation(response, '发布合同状态已更新');
}

function runTransitionCommand(row, command) {
  if (command === 'record-platform-approved') {
    return runAction(row, 'record-platform-review', {
      result_status: 'approved',
      scheduled_at: new Date(Date.now() + 5 * 60 * 1000).toISOString()
    });
  }
  if (command === 'record-platform-rejected') {
    return runAction(row, 'record-platform-review', { result_status: 'rejected' });
  }
  if (command === 'record-release-success') {
    return runAction(row, 'record-release-result', {
      result_status: 'released',
      evidence_refs: ['external-platform-result:masked']
    });
  }
  if (command === 'record-release-failed') {
    return runAction(row, 'record-release-result', {
      result_status: 'failed',
      evidence_refs: ['external-platform-result:masked']
    });
  }
  return runAction(row, command);
}

function transitionActions(row) {
  const actions = {
    built: [{ command: 'upload', label: '记录已上传' }],
    uploaded: [{ command: 'submit-platform-review', label: '记录已提交平台审核' }],
    platform_review: [
      { command: 'record-platform-approved', label: '记录平台审核通过' },
      { command: 'record-platform-rejected', label: '记录平台审核拒绝' }
    ],
    scheduled: [{ command: 'start-release', label: '记录开始发布' }],
    releasing: [
      { command: 'record-release-success', label: '记录发布成功' },
      { command: 'record-release-failed', label: '记录发布失败' }
    ],
    released: [
      { command: 'start-observation', label: '进入观察期' },
      { command: 'request-rollback', label: '申请回滚' }
    ],
    observing: [
      { command: 'complete', label: '完成发布合同' },
      { command: 'request-rollback', label: '申请回滚' }
    ],
    release_failed: [{ command: 'request-rollback', label: '申请回滚' }],
    rollback_required: [{ command: 'execute-rollback', label: '记录回滚完成' }]
  };
  return actions[row.status] || [];
}

function finishMutation(response, message, close) {
  if (!response.success) {
    ElMessage.error(response.message);
    return;
  }
  close?.();
  ElMessage.success(message);
  load();
}

load();
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.summary-card {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px 12px;
  padding: 16px;
  border: 1px solid #dbe4ef;
  border-left: 4px solid #64748b;
  border-radius: 10px;
  background: #fff;
}
.summary-card--warning { border-left-color: #d97706; }
.summary-card--success { border-left-color: #059669; }
.summary-card--info { border-left-color: #2563eb; }
.summary-card span { color: #64748b; font-size: 13px; }
.summary-card strong { grid-row: span 2; font-size: 28px; line-height: 1; }
.summary-card small { color: #94a3b8; }
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  margin-bottom: 14px;
  border: 1px solid #dbe4ef;
  border-radius: 10px;
  background: #fff;
}
.filter-bar :deep(.el-select) { width: 150px; }
.filter-bar__hint { margin-left: auto; color: #64748b; font-size: 12px; }
.contract-table { border-radius: 10px; }
.contract-link { display: block; padding: 0; font-weight: 650; }
.commit { display: block; margin-top: 4px; color: #94a3b8; font-family: ui-monospace, monospace; }
.gate-cell { display: grid; grid-template-columns: 1fr 36px; align-items: center; gap: 8px; font-size: 12px; }
.drawer-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.drawer-heading h2 { margin: 4px 0 0; font-size: 22px; }
.drawer-heading small { color: #64748b; }
.detail-block { margin: 18px 0 22px; }
.detail-block :deep(.el-tag) { margin: 2px 6px 2px 0; }
h3 { margin: 24px 0 10px; font-size: 15px; }
.evidence-list { display: grid; gap: 8px; }
.evidence-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.evidence-row div { display: grid; gap: 4px; min-width: 0; }
.evidence-row small { overflow: hidden; color: #64748b; text-overflow: ellipsis; white-space: nowrap; }
.approval-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.approval-card { display: grid; gap: 5px; padding: 13px; border: 1px solid #e2e8f0; border-radius: 8px; }
.approval-card span, .approval-card small { color: #64748b; }
.approval-card small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }
.form-span-2 { grid-column: span 2; }
.dialog-form { margin-top: 16px; }
code { overflow-wrap: anywhere; }

@media (max-width: 1000px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-bar { flex-wrap: wrap; }
  .filter-bar__hint { width: 100%; margin-left: 0; }
}
@media (max-width: 640px) {
  .summary-grid, .approval-grid, .form-grid { grid-template-columns: 1fr; }
  .form-span-2 { grid-column: span 1; }
  .filter-bar :deep(.el-select) { width: calc(50% - 5px); }
}
</style>
