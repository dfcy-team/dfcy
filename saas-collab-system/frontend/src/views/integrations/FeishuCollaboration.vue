<template>
  <AppPage
    eyebrow="FEISHU COLLABORATION"
    title="飞书协同"
    subtitle="在一个工作台统一管理飞书应用、身份、消息预警、综合报表与审批映射。"
    boundary-note="审批办理仍在“流程协同 > 审批中心”完成；本页只管理飞书集成关系。密钥保存后不会回显。"
    :capability="capability"
  >
    <template #action><el-button :loading="loading" @click="loadActive">刷新当前页签</el-button></template>

    <el-tabs v-model="activeTab" class="feishu-tabs" @tab-change="switchTab">
      <el-tab-pane v-for="tab in tabs" :key="tab.name" :label="tab.label" :name="tab.name" />
    </el-tabs>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert" />

    <section v-if="activeTab === 'connection'" v-loading="loading" class="panel">
      <header class="panel__header"><div><h2>应用连接</h2><p>配置企业自建应用和官方事件回调，不在前端保存任何凭据。</p></div><el-tag :type="connectionStatusType">{{ connectionStatusLabel }}</el-tag></header>
      <el-form :model="connection" label-position="top" class="form-grid">
        <el-form-item label="App ID"><el-input v-model.trim="connection.app_id" placeholder="cli_xxxxxxxxx" /></el-form-item>
        <el-form-item label="API 环境"><el-select v-model="connection.domain"><el-option label="飞书（中国版）" value="feishu" /><el-option label="Lark（国际版）" value="lark" /></el-select></el-form-item>
        <el-form-item label="App Secret"><el-input v-model="secrets.app_secret" type="password" show-password :placeholder="connection.credential_configured ? '已配置，留空则不更新' : '请输入 App Secret'" /></el-form-item>
        <el-form-item label="Verification Token"><el-input v-model="secrets.verification_token" type="password" show-password :placeholder="connection.verification_token_configured ? '已配置，留空则不更新' : '请输入 Verification Token'" /></el-form-item>
        <el-form-item label="Encrypt Key"><el-input v-model="secrets.encrypt_key" type="password" show-password :placeholder="connection.encrypt_key_configured ? '已配置，留空则不更新' : '可选：事件加密密钥'" /></el-form-item>
        <el-form-item label="事件回调地址"><el-input :model-value="connection.callback_url || '保存应用后由后端生成'" readonly /></el-form-item>
        <el-form-item label="启用飞书集成"><el-switch v-model="connection.enabled" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <div v-if="connection.menu_capabilities?.length" class="scope-list"><h3>菜单能力与权限</h3><div v-for="item in connection.menu_capabilities" :key="item.menu" class="scope-row"><strong>{{ item.menu }}</strong><span>基础权限：{{ item.required_scopes?.join('、') || '无额外API权限' }}<br v-if="item.optional_scopes?.length"/><span v-if="item.optional_scopes?.length">按功能选用：{{ item.optional_scopes.join('、') }}</span><br/>{{ item.note }}</span><el-tag size="small">{{ feishuLabels[item.status] || item.status }}</el-tag></div></div>
      <div class="panel__actions"><el-button :loading="testing" :disabled="testing || !canManageCurrent" :title="manageHint" @click="testConnection">测试连接</el-button><el-button type="primary" :loading="saving" :disabled="!canManageCurrent" :title="manageHint" @click="saveConnection">保存连接</el-button></div>
    </section>

    <section v-else class="panel">
      <header class="panel__header">
        <div><h2>{{ currentMeta.title }}</h2><p>{{ currentMeta.description }}</p></div>
        <el-button v-if="currentMeta.resource !== 'operations' && currentMeta.resource !== 'identities'" type="primary" :disabled="!canManageCurrent" :title="manageHint" @click="openCreate">{{ currentMeta.createLabel }}</el-button>
      </header>
      <div v-if="activeTab === 'operations'" class="filters">
        <el-select v-model="operationType" clearable placeholder="全部类型" @change="loadActive"><el-option label="消息投递" value="notification" /><el-option label="报表运行" value="report" /><el-option label="审批事件" value="approval" /><el-option label="回调事件" value="event" /></el-select>
        <el-select v-model="operationStatus" clearable placeholder="全部状态" @change="loadActive"><el-option label="待处理" value="pending" /><el-option label="成功" value="success" /><el-option label="失败" value="failed" /><el-option label="处理中" value="processing" /><el-option label="已跳过" value="skipped" /></el-select>
      </div>
      <el-table v-if="activeTab === 'identity'" v-loading="loading" :data="rows" border stripe :empty-text="loading ? '正在加载' : currentMeta.emptyText">
        <el-table-column label="系统用户" min-width="180">
          <template #default="{ row }"><div class="user-cell"><strong>{{ row.full_name || row.name || row.username || '—' }}</strong><span v-if="row.username">{{ row.username }}</span></div></template>
        </el-table-column>
        <el-table-column prop="department" label="系统部门" min-width="150"><template #default="{ row }">{{ row.department || '—' }}</template></el-table-column>
        <el-table-column prop="open_id" label="飞书用户" min-width="210"><template #default="{ row }"><div class="user-cell"><strong>{{ row.feishu_name || (row.open_id ? '已绑定' : '未绑定') }}</strong><span>{{ row.open_id || '—' }}</span></div></template></el-table-column>
        <el-table-column label="飞书部门" min-width="150"><template #default="{ row }">{{ displayValue(row, 'feishu_department_name') !== '—' ? displayValue(row, 'feishu_department_name') : displayValue(row, 'department_ids') }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.open_id ? 'success' : 'info'">{{ row.open_id ? '已绑定' : '未绑定' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="210" fixed="right"><template #default="{ row }"><el-button link type="primary" :loading="candidateUserId === row.system_user_id" :disabled="!canManageCurrent" :title="manageHint" @click="queryCandidates(row)">{{ row.open_id ? '重新选择' : '查询飞书用户' }}</el-button><el-button v-if="row.id" link type="danger" :disabled="!canManageCurrent" :title="manageHint" @click="unbindIdentity(row)">解绑</el-button></template></el-table-column>
      </el-table>
      <el-table v-else-if="activeTab !== 'operations'" v-loading="loading" :data="rows" border stripe :empty-text="loading ? '正在加载' : currentMeta.emptyText">
        <el-table-column v-for="column in currentMeta.columns" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 130">
          <template #default="{ row }">{{ displayValue(row, column.prop) }}</template>
        </el-table-column>
        <el-table-column v-if="currentMeta.resource !== 'operations'" label="操作" min-width="210" fixed="right">
          <template #default="{ row }"><el-button v-if="activeTab === 'notification'" link type="success" :disabled="!canManageCurrent || !row.enabled" @click="runNotification(row)">立即发送</el-button><el-button v-if="activeTab === 'report'" link type="primary" :disabled="!canManageCurrent" @click="previewReport(row)">预览</el-button><el-button v-if="activeTab === 'report'" link type="success" :disabled="!canManageCurrent || !row.enabled" @click="runReport(row)">立即推送</el-button><el-button link type="primary" :disabled="!canManageCurrent" :title="manageHint" @click="openEdit(row)">编辑</el-button><el-button link type="danger" :disabled="!canManageCurrent" :title="manageHint" @click="remove(row)">删除</el-button></template>
        </el-table-column>
      </el-table>
      <el-table v-if="activeTab === 'operations'" v-loading="loading" :data="rows" border stripe :empty-text="currentMeta.emptyText" class="operation-table">
        <el-table-column label="类型" min-width="110"><template #default="{ row }">{{ displayValue(row, 'operation_type') }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="{ row }">{{ displayValue(row, 'status') }}</template></el-table-column><el-table-column prop="created_at" label="时间" min-width="160"/><el-table-column label="执行详情" min-width="240"><template #default="{ row }"><div class="user-cell"><span v-for="(value, key) in row.masked_detail || {}" :key="key">{{ operationLabels[key] || key }}：{{ value }}</span></div></template></el-table-column><el-table-column label="操作" width="100"><template #default="{ row }"><el-button v-if="row.status === 'failed'" link type="primary" :disabled="!canManageCurrent" @click="retryOperation(row)">重试</el-button></template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" :title="editingId ? `编辑${currentMeta.singular}` : currentMeta.createLabel" width="620px">
      <el-form :model="editor" label-position="top">
        <template v-if="activeTab === 'identity'">
          <el-form-item label="系统用户 ID"><el-input v-model.trim="editor.system_user_id" placeholder="请输入系统用户 ID" /></el-form-item>
          <el-form-item label="飞书 Open ID"><el-input v-model.trim="editor.open_id" placeholder="ou_xxxxxxxxx" /></el-form-item>
          <el-form-item label="飞书 User ID"><el-input v-model.trim="editor.user_id" /></el-form-item>
          <el-form-item label="飞书 Union ID"><el-input v-model.trim="editor.union_id" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="名称"><el-input v-model.trim="editor.name" :placeholder="`请输入${currentMeta.singular}名称`" /></el-form-item>
          <el-form-item v-if="activeTab === 'notification'" label="消息场景"><el-select v-model="editor.scene"><el-option label="库存预警" value="inventory_alert" /><el-option label="经营预警" value="business_alert" /><el-option label="同步失败" value="sync_failed" /><el-option label="审批结果" value="approval_result" /></el-select></el-form-item>
          <el-form-item v-if="activeTab === 'report'" label="报表类型"><el-select v-model="editor.report_type"><el-option v-for="item in reportTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item v-if="activeTab === 'report'" label="推送周期"><el-select v-model="editor.schedule"><el-option label="每日" value="daily" /><el-option label="每周" value="weekly" /><el-option label="每月" value="monthly" /></el-select></el-form-item>
          <el-form-item v-if="activeTab === 'approval'" label="本地审批类型"><el-select v-model="editor.approval_type"><el-option v-for="item in approvalTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <template v-if="['notification', 'report', 'approval'].includes(activeTab)">
            <el-form-item label="启用规则"><el-switch v-model="editor.enabled" active-text="启用" inactive-text="停用" /></el-form-item>
            <el-form-item label="接收人（已绑定飞书身份）"><el-select v-model="editor.recipient_user_ids" multiple filterable collapse-tags placeholder="选择系统用户"><el-option v-for="user in boundUsers" :key="user.system_user_id" :label="`${user.full_name || user.username || user.system_user_id} · ${user.feishu_name || user.open_id}`" :value="user.system_user_id" /></el-select></el-form-item>
            <el-form-item v-if="activeTab === 'notification'" label="消息格式"><el-select v-model="editor.format"><el-option label="纯文本" value="text"/><el-option label="消息卡片" value="card"/></el-select></el-form-item>
            <el-form-item v-if="activeTab === 'notification'" label="消息内容"><el-input v-model="editor.message" type="textarea" :rows="3" placeholder="填写将发送给所选用户的内容" /></el-form-item>
          <el-form-item v-if="activeTab === 'report'" label="报表发送时间（北京时间；每周一/每月1日）"><el-time-select v-model="editor.hour" start="00:00" step="01:00" end="23:00" placeholder="选择小时" /></el-form-item>
            <el-form-item v-if="activeTab === 'report'" label="报表格式"><el-select v-model="editor.format"><el-option label="消息卡片" value="card"/><el-option label="文件" value="file"/></el-select></el-form-item>
          </template>
          <el-collapse><el-collapse-item title="高级配置（仅支持当前页签字段）" name="advanced"><el-input v-model="editor.configText" type="textarea" :rows="5" placeholder="可选：报表起止日期filters" /><p>保存按当前页签转换旧规则；旧飞书 Approval Code 不再使用，审批在本系统处理。</p></el-collapse-item></el-collapse>
        </template>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!canManageCurrent" :title="manageHint" @click="saveResource">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="candidateDialogVisible" title="选择飞书用户" width="900px">
      <div v-if="candidateSystemUser" class="candidate-summary">正在为系统用户 <strong>{{ candidateSystemUser.full_name || candidateSystemUser.name || candidateSystemUser.username }}</strong> 查询匹配候选。请选择并确认，不会仅凭姓名自动绑定。</div>
      <div class="manual-open-id">
        <el-input v-model.trim="manualOpenId" placeholder="自动查找无结果时，可输入飞书 Open ID（ou_...）验证" clearable @keyup.enter="verifyManualOpenId" />
        <el-button type="primary" plain :loading="manualChecking" :disabled="!manualOpenId || manualChecking" @click="verifyManualOpenId">验证 Open ID</el-button>
      </div>
      <p class="manual-open-id__help">验证会实时读取飞书用户资料；只有验证通过后才能选择并绑定，不支持直接写入未经验证的 Open ID。</p>
      <el-alert v-if="candidateSystemUser?.open_id" :title="`该系统用户已绑定 ${candidateSystemUser.open_id}；确认其他候选将替换原绑定。`" type="warning" show-icon :closable="false" class="binding-alert" />
      <el-alert v-if="candidateMessage" :title="candidateMessage" :type="candidateMessageType" show-icon :closable="false" class="binding-alert" />
      <el-table v-loading="candidateLoading" :data="candidates" :empty-text="candidateLoading ? '正在查询飞书通讯录' : (candidateMessage || '未找到匹配的飞书用户')" border highlight-current-row @current-change="selectCandidate">
        <el-table-column label="选择" width="64"><template #default="{ row }"><el-radio :model-value="selectedCandidate?.open_id" :label="row.open_id" @change="selectCandidate(row)"><span /></el-radio></template></el-table-column>
        <el-table-column prop="name" label="飞书姓名" min-width="120" />
        <el-table-column label="部门" min-width="140"><template #default="{ row }">{{ row.department_name || displayValue(row, 'department_names') }}</template></el-table-column>
        <el-table-column label="匹配依据" min-width="170"><template #default="{ row }"><el-tag :type="row.match_level === 'exact_contact' ? 'success' : (['name_department', 'manual_open_id'].includes(row.match_level) ? 'primary' : 'warning')">{{ row.match_reason || '人工候选' }}</el-tag></template></el-table-column>
        <el-table-column label="邮箱 / 手机" min-width="180"><template #default="{ row }"><div class="user-cell"><span>{{ row.email || '—' }}</span><span>{{ row.phone || '—' }}</span></div></template></el-table-column>
        <el-table-column prop="open_id" label="Open ID" min-width="210" />
      </el-table>
      <template #footer><el-button @click="candidateDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!selectedCandidate" @click="confirmIdentityBinding">确认绑定</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { feishuRuleConfig, feishuRequestId, feishuLabels } from '../../utils/feishuRule';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { bindFeishuIdentity, createFeishuResource, deleteFeishuResource, fetchFeishuConnection, fetchFeishuIdentityCandidates, fetchFeishuOperations, fetchFeishuResources, notifyFeishuApproval, previewFeishuReport, retryFeishuOperation, runFeishuNotification, runFeishuReport, testFeishuConnection, updateFeishuConnection, updateFeishuResource } from '../../api/feishu';

const route = useRoute(); const router = useRouter();
const auth = useAuthStore();
const tabs = [{ name: 'connection', label: '应用连接' }, { name: 'identity', label: '身份映射' }, { name: 'notification', label: '消息与预警' }, { name: 'report', label: '报表推送' }, { name: 'approval', label: '审批映射' }, { name: 'operations', label: '运行与事件' }];
const metadata = {
  identity: { resource: 'identities', title: '身份映射', singular: '身份映射', description: '系统用户全部直接展示；查询飞书候选后，由用户人工确认绑定。', createLabel: '新增映射', emptyText: '暂无可配置的系统用户。', columns: [] },
  notification: { resource: 'notifications', title: '消息与预警', singular: '通知规则', description: '为库存、经营、同步异常和审批结果配置飞书投递策略。', createLabel: '新建通知规则', emptyText: '暂无消息与预警规则。', columns: [{ prop: 'name', label: '规则名称' }, { prop: 'scene', label: '业务场景' }, { prop: 'format', label: '消息格式' }, { prop: 'enabled', label: '状态' }] },
  report: { resource: 'reports', title: '报表推送', singular: '报表任务', description: '按接收人现有数据权限生成销售、退款、财务和库存汇总；支持定时卡片或CSV附件推送。', createLabel: '新建报表任务', emptyText: '暂无报表推送任务。', columns: [{ prop: 'name', label: '任务名称' }, { prop: 'report_type', label: '报表类型' }, { prop: 'schedule', label: '周期' }, { prop: 'hour', label: '推送时间（北京）' }, { prop: 'enabled', label: '状态' }] },
  approval: { resource: 'approvals', title: '审批映射', singular: '审批映射', description: '将本地采购、价格、刊登等审批类型关联到飞书通知接收人；此处不创建飞书原生审批。', createLabel: '新建审批映射', emptyText: '暂无审批映射。', columns: [{ prop: 'name', label: '映射名称' }, { prop: 'approval_type', label: '本地审批类型' }, { prop: 'enabled', label: '状态' }] },
  operations: { resource: 'operations', title: '运行与事件', description: '查看消息投递、报表运行、审批同步和回调处理结果。', emptyText: '暂无飞书运行或事件记录。', columns: [{ prop: 'operation_type', label: '类型' }, { prop: 'business_reference', label: '业务对象' }, { prop: 'status', label: '状态' }, { prop: 'request_id', label: '请求 ID' }, { prop: 'created_at', label: '发生时间' }] }
};
const reportTypes = [{ label: '综合报表', value: 'comprehensive' }, { label: '销售报表', value: 'sales' }, { label: '库存报表', value: 'inventory' }];
const approvalTypes = [{ label: '采购审批', value: 'purchase' }, { label: '价格审批', value: 'price' }, { label: '刊登审批', value: 'listing' }, { label: '清仓审批', value: 'clearance' }, { label: '财务审批', value: 'finance' }, { label: '报表导出审批', value: 'report_export' }];
const validTabs = new Set(tabs.map((item) => item.name));
const activeTab = ref(validTabs.has(String(route.query.tab)) ? String(route.query.tab) : 'connection');
const loading = ref(false); const saving = ref(false); const testing = ref(false); const error = ref(''); const capability = ref(useMock ? 'mock' : 'pending'); const rows = ref([]); const boundUsers = ref([]); const dialogVisible = ref(false); const editingId = ref(null); const operationType = ref(''); const operationStatus = ref('');
const candidateDialogVisible = ref(false); const candidateLoading = ref(false); const candidateUserId = ref(null); const candidateSystemUser = ref(null); const candidates = ref([]); const selectedCandidate = ref(null); const candidateMessage = ref(''); const candidateMessageType = ref('info'); const manualOpenId = ref(''); const manualChecking = ref(false);
const connection = reactive({ app_id: '', domain: 'feishu', enabled: false, status: 'not_configured', callback_url: '', credential_configured: false, verification_token_configured: false, encrypt_key_configured: false });
const operationLabels = { recipient_user_id: '接收用户', message_id: '消息 ID', attempts: '尝试次数', error_message: '错误', reference: '关联对象' };
const secrets = reactive({ app_secret: '', verification_token: '', encrypt_key: '' }); const editor = reactive({});
const currentMeta = computed(() => metadata[activeTab.value] || metadata.identity);
const managePermissions = { connection: 'feishu.connection.manage', identity: 'feishu.identity.manage', notification: 'feishu.notification.manage', report: 'feishu.report.manage', approval: 'feishu.approval.manage', operations: 'feishu.operations.retry' };
const canManageCurrent = computed(() => Boolean(managePermissions[activeTab.value] && auth.hasPermission(managePermissions[activeTab.value])));
const manageHint = computed(() => canManageCurrent.value ? '' : `需要 ${managePermissions[activeTab.value] || 'feishu.view'} 权限`);
const connectionStatusLabel = computed(() => ({ connected: '已连接', active: '已连接', disabled: '已停用', error: '连接异常', not_configured: '未配置', configured: '已配置', unconfigured: '未配置' })[connection.status] || connection.status || '未配置');
const connectionStatusType = computed(() => ({ connected: 'success', active: 'success', disabled: 'info', error: 'danger', not_configured: 'warning' })[connection.status] || 'info');

function displayValue(row, prop) { const value = row?.[prop] ?? row?.config?.[prop]; if (prop === 'hour' && Number.isInteger(value)) return `${String(value).padStart(2, '0')}:00`; if (typeof value === 'boolean') return value ? '启用' : '停用'; if (Array.isArray(value)) return value.length ? value.join('、') : '—'; return value === null || value === undefined || value === '' ? '—' : (feishuLabels[value] || value); }
function listRows(response) { const data = response?.data; return Array.isArray(data) ? data : (data?.items || data?.results || []); }
function setApiState(response) { capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded'); if (!response?.success) error.value = response?.message || '请求飞书集成数据失败。'; }
async function loadActive() { loading.value = true; error.value = ''; const response = activeTab.value === 'connection' ? await fetchFeishuConnection() : activeTab.value === 'operations' ? await fetchFeishuOperations({ operation_type: operationType.value || undefined, status: operationStatus.value || undefined }) : await fetchFeishuResources(currentMeta.value.resource); setApiState(response); if (response?.success) { if (activeTab.value === 'connection') Object.assign(connection, response.data || {}); else { const items = listRows(response); rows.value = activeTab.value === 'identity' ? items.map((item) => ({ ...item, ...(item.mapping || {}) })) : items; } } loading.value = false; }
function switchTab(name) { router.replace({ query: { ...route.query, tab: name === 'connection' ? undefined : name } }); loadActive(); }
async function saveConnection() { if (!canManageCurrent.value) return; saving.value = true; error.value = ''; const payload = { app_id: connection.app_id, domain: connection.domain, enabled: connection.enabled }; for (const [key, value] of Object.entries(secrets)) if (value) payload[key] = value; const response = await updateFeishuConnection(payload); setApiState(response); if (response?.success) { Object.assign(connection, response.data || {}); Object.assign(secrets, { app_secret: '', verification_token: '', encrypt_key: '' }); ElMessage.success('飞书应用连接已保存'); } saving.value = false; }
function resetEditor(row = {}) { for (const key of Object.keys(editor)) delete editor[key]; Object.assign(editor, row, { configText: JSON.stringify(row.config || {}, null, 2) }); }
async function loadBoundUsers() { const response = await fetchFeishuResources('identities'); if (response?.success) boundUsers.value = listRows(response).map((item) => ({ ...item, ...(item.mapping || {}) })).filter((item) => item.open_id); }
function openCreate() { if (!canManageCurrent.value) return; editingId.value = null; resetEditor({ enabled: false, recipient_user_ids: [], scene: 'business_alert', report_type: 'comprehensive', approval_type: 'purchase', format: activeTab.value === 'notification' ? 'text' : 'card', schedule: 'daily', hour: '09:00' }); loadBoundUsers(); dialogVisible.value = true; }
function openEdit(row) { if (!canManageCurrent.value) return; editingId.value = row.id; resetEditor({ ...row, ...(row.config || {}) }); editor.recipient_user_ids ||= []; if (editor.approval_type === 'pricing') editor.approval_type = 'price'; editor.hour = typeof editor.hour === 'number' ? `${String(editor.hour).padStart(2, '0')}:00` : (editor.hour || '09:00'); loadBoundUsers(); dialogVisible.value = true; }
function stableCode() { return editor.code || `${currentMeta.value.resource}_${Date.now()}`; }
function idempotencyKey() { return feishuRequestId(); }
async function testConnection() { testing.value = true; const response = await testFeishuConnection(); setApiState(response); ElMessage[response?.success ? 'success' : 'error'](response?.success ? '连接验证成功（未发送外部消息）' : response?.message || '连接验证失败'); testing.value = false; }
async function runNotification(row) { try { await ElMessageBox.confirm(`将立即向规则“${row.name}”中已绑定的接收人发送真实飞书消息，继续吗？`, '确认真实投递', { type: 'warning', confirmButtonText: '确认发送' }); } catch (_error) { return; } const response = await runFeishuNotification(row.id, idempotencyKey()); setApiState(response); if (response?.success) ElMessage.success(`执行已受理：${feishuLabels[response.data?.status] || '已提交'}`); }
async function previewReport(row) { const response = await previewFeishuReport(row.id); setApiState(response); if (response?.success) await ElMessageBox.alert(`${response.data?.title || '报表预览'}\n\n${response.data?.summary || ''}\n\n生成时间：${response.data?.generated_at || '—'}`, '报表预览', { confirmButtonText: '关闭', customClass: 'feishu-report-preview' }); }
async function runReport(row) { try { await ElMessageBox.confirm(`将立即向“${row.name}”任务中已绑定的接收人发送真实报表，继续吗？`, '确认真实推送', { type: 'warning', confirmButtonText: '确认推送' }); } catch (_error) { return; } const response = await runFeishuReport(row.id, idempotencyKey()); setApiState(response); if (response?.success) ElMessage.success(`执行已受理：${feishuLabels[response.data?.status] || '已提交'}`); }
async function retryOperation(row) { try { await ElMessageBox.confirm('将重试该失败的飞书操作，可能再次向接收人发送消息。继续吗？', '确认重试', { type: 'warning' }); } catch (_error) { return; } const response = await retryFeishuOperation(row.id); setApiState(response); if (response?.success) { ElMessage.success('重试已受理'); await loadActive(); } }
async function saveResource() { if (!canManageCurrent.value) return; let config; try { config = feishuRuleConfig(activeTab.value, editor, editor.configText?.trim() ? JSON.parse(editor.configText) : {}); } catch (error) { ElMessage.error(error.message || '高级规则配置必须是有效 JSON'); return; } let payload; if (activeTab.value === 'identity') { payload = { ...editor }; delete payload.configText; } else { payload = { name: editor.name, code: stableCode(), enabled: editor.enabled !== false, config }; } saving.value = true; const response = editingId.value ? await updateFeishuResource(currentMeta.value.resource, editingId.value, payload) : await createFeishuResource(currentMeta.value.resource, payload); setApiState(response); if (response?.success) { dialogVisible.value = false; ElMessage.success('已保存'); await loadActive(); } saving.value = false; }
async function remove(row) { if (!canManageCurrent.value) return; try { await ElMessageBox.confirm(`确定删除“${row.name || row.username || row.id}”吗？`, '删除确认', { type: 'warning' }); } catch (_error) { return; } const response = await deleteFeishuResource(currentMeta.value.resource, row.id); setApiState(response); if (response?.success) { ElMessage.success('已删除'); await loadActive(); } }
async function queryCandidates(row) { if (!canManageCurrent.value) return; const systemUserId = row.system_user_id; candidateSystemUser.value = row; candidateUserId.value = systemUserId; candidateLoading.value = true; selectedCandidate.value = null; candidates.value = []; manualOpenId.value = ''; candidateMessage.value = ''; candidateMessageType.value = 'info'; candidateDialogVisible.value = true; const response = await fetchFeishuIdentityCandidates(systemUserId); setApiState(response); if (response?.success) { candidates.value = response?.data?.candidates || []; candidateMessage.value = candidates.value.length ? `已找到 ${candidates.value.length} 个候选，请核对 Open ID 和匹配依据后绑定。` : '未找到匹配的飞书用户，可手动输入 Open ID 验证。'; candidateMessageType.value = candidates.value.length ? 'success' : 'warning'; } else { candidateMessage.value = `${response?.message || '飞书用户自动查询失败。'} 可手动输入 Open ID 验证。`; candidateMessageType.value = 'warning'; } candidateLoading.value = false; candidateUserId.value = null; }
async function verifyManualOpenId() { if (!candidateSystemUser.value || !manualOpenId.value || manualChecking.value) return; selectedCandidate.value = null; if (!/^ou_[A-Za-z0-9_-]{1,128}$/.test(manualOpenId.value)) { candidates.value = []; candidateMessage.value = '请输入有效的飞书 Open ID（以 ou_ 开头）。'; candidateMessageType.value = 'error'; return; } manualChecking.value = true; const response = await fetchFeishuIdentityCandidates(candidateSystemUser.value.system_user_id, { open_id: manualOpenId.value }); setApiState(response); if (response?.success) { const candidate = response?.data?.candidates?.[0]; candidates.value = candidate ? [candidate] : []; selectedCandidate.value = candidate || null; candidateMessage.value = candidate ? `Open ID ${candidate.open_id} 验证通过，请核对用户信息后确认绑定。` : '该 Open ID 未返回可绑定用户。'; candidateMessageType.value = candidate ? 'success' : 'warning'; } else { candidates.value = []; candidateMessage.value = response?.message || 'Open ID 验证失败，请检查标识、通讯录权限和应用可用范围。'; candidateMessageType.value = 'error'; } manualChecking.value = false; }
function selectCandidate(row) { selectedCandidate.value = row || null; }
async function confirmIdentityBinding() { if (!canManageCurrent.value || !candidateSystemUser.value || !selectedCandidate.value) return; const candidate = selectedCandidate.value; const currentOpenId = candidateSystemUser.value.open_id; if (currentOpenId && currentOpenId !== candidate.open_id) { try { await ElMessageBox.confirm(`该系统用户当前已绑定 ${currentOpenId}，确认替换为 ${candidate.open_id}？`, '替换飞书绑定', { type: 'warning', confirmButtonText: '确认替换' }); } catch (_error) { return; } } const systemUserId = candidateSystemUser.value.system_user_id; const payload = { open_id: candidate.open_id, user_id: candidate.user_id || '', union_id: candidate.union_id || '', department_ids: candidate.department_ids || [] }; saving.value = true; const response = await bindFeishuIdentity(systemUserId, payload); setApiState(response); if (response?.success) { candidateDialogVisible.value = false; ElMessage.success(currentOpenId && currentOpenId !== candidate.open_id ? '飞书绑定已替换' : '飞书用户已绑定'); await loadActive(); } saving.value = false; }
async function unbindIdentity(row) { if (!canManageCurrent.value || !row.id) return; try { await ElMessageBox.confirm(`确认解除系统用户“${row.full_name || row.username}”与飞书用户 ${row.open_id || ''} 的绑定？不会删除任何用户。`, '解除飞书绑定', { type: 'warning', confirmButtonText: '确认解绑' }); } catch (_error) { return; } const response = await deleteFeishuResource('identities', row.id); setApiState(response); if (response?.success) { ElMessage.success('飞书绑定已解除'); await loadActive(); } }
watch(() => route.query.tab, (value) => { const next = validTabs.has(String(value)) ? String(value) : 'connection'; if (next !== activeTab.value) { activeTab.value = next; loadActive(); } });
onMounted(loadActive);
</script>

<style scoped>
:global(.feishu-report-preview .el-message-box__message) { white-space: pre-line; }
.feishu-tabs { margin-bottom: 18px; overflow-x: auto; }
.page-alert { margin-bottom: 16px; }
.panel { padding: 20px; border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; }
.panel__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
.panel__header h2 { margin: 0; color: #172033; font-size: 18px; }
.panel__header p { margin: 7px 0 0; color: #64748b; line-height: 1.55; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.panel__actions { display: flex; justify-content: flex-end; padding-top: 8px; }
.filters { display: flex; gap: 12px; margin-bottom: 16px; }
.filters .el-select { width: 180px; }
.user-cell { display: flex; flex-direction: column; gap: 3px; }
.user-cell span { color: #64748b; font-size: 12px; }
.candidate-summary { margin-bottom: 14px; color: #475569; line-height: 1.6; }
.binding-alert { margin-bottom: 14px; }
.manual-open-id { display: flex; gap: 10px; margin-bottom: 6px; }
.manual-open-id .el-input { flex: 1; }
.manual-open-id__help { margin: 0 0 14px; color: #64748b; font-size: 12px; line-height: 1.5; }
.scope-list { margin-top: 18px; border-top: 1px solid #e5e7eb; padding-top: 14px; }.scope-list h3 { margin: 0 0 8px; font-size: 14px; }.scope-row { display: grid; grid-template-columns: minmax(100px, .7fr) 2fr auto; gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-size: 13px; }.schedule-control { display: flex; gap: 10px; width: 100%; }.schedule-control > * { flex: 1; }
@media (max-width: 720px) { .panel__header { flex-direction: column; } .form-grid { grid-template-columns: 1fr; } }
@media (max-width: 540px) { .panel { padding: 14px; }.filters { flex-wrap: wrap; }.filters .el-select { width: 100%; }.scope-row { grid-template-columns: 1fr auto; }.scope-row span { grid-column: 1 / -1; }.schedule-control { flex-direction: column; } }
</style>
