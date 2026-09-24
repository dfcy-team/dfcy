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
      <div class="panel__actions"><el-button type="primary" :loading="saving" :disabled="!canManageCurrent" :title="manageHint" @click="saveConnection">保存连接</el-button></div>
    </section>

    <section v-else class="panel">
      <header class="panel__header">
        <div><h2>{{ currentMeta.title }}</h2><p>{{ currentMeta.description }}</p></div>
        <el-button v-if="currentMeta.resource !== 'operations' && currentMeta.resource !== 'identities'" type="primary" :disabled="!canManageCurrent" :title="manageHint" @click="openCreate">{{ currentMeta.createLabel }}</el-button>
      </header>
      <div v-if="activeTab === 'operations'" class="filters">
        <el-select v-model="operationType" clearable placeholder="全部类型" @change="loadActive"><el-option label="消息投递" value="notification" /><el-option label="报表运行" value="report" /><el-option label="审批事件" value="approval" /><el-option label="回调事件" value="event" /></el-select>
        <el-select v-model="operationStatus" clearable placeholder="全部状态" @change="loadActive"><el-option label="成功" value="success" /><el-option label="失败" value="failed" /><el-option label="处理中" value="processing" /></el-select>
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
      <el-table v-else v-loading="loading" :data="rows" border stripe :empty-text="loading ? '正在加载' : currentMeta.emptyText">
        <el-table-column v-for="column in currentMeta.columns" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 130">
          <template #default="{ row }">{{ displayValue(row, column.prop) }}</template>
        </el-table-column>
        <el-table-column v-if="currentMeta.resource !== 'operations'" label="操作" width="150" fixed="right">
          <template #default="{ row }"><el-button link type="primary" :disabled="!canManageCurrent" :title="manageHint" @click="openEdit(row)">编辑</el-button><el-button link type="danger" :disabled="!canManageCurrent" :title="manageHint" @click="remove(row)">删除</el-button></template>
        </el-table-column>
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
          <el-form-item v-if="activeTab === 'approval'" label="飞书 Approval Code"><el-input v-model.trim="editor.approval_code" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" /></el-form-item>
          <el-form-item label="接收与规则配置（JSON）"><el-input v-model="editor.configText" type="textarea" :rows="6" placeholder='{"enabled": true}' /></el-form-item>
        </template>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!canManageCurrent" :title="manageHint" @click="saveResource">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="candidateDialogVisible" title="选择飞书用户" width="760px">
      <div v-if="candidateSystemUser" class="candidate-summary">正在为系统用户 <strong>{{ candidateSystemUser.full_name || candidateSystemUser.name || candidateSystemUser.username }}</strong> 查询匹配候选。请选择并确认，不会仅凭姓名自动绑定。</div>
      <el-alert v-if="candidateSystemUser?.open_id" :title="`该系统用户已绑定 ${candidateSystemUser.open_id}；确认其他候选将替换原绑定。`" type="warning" show-icon :closable="false" class="binding-alert" />
      <el-alert v-if="candidateMessage" :title="candidateMessage" :type="candidateMessageType" show-icon :closable="false" class="binding-alert" />
      <el-table v-loading="candidateLoading" :data="candidates" :empty-text="candidateLoading ? '正在查询飞书通讯录' : (candidateMessage || '未找到匹配的飞书用户')" border highlight-current-row @current-change="selectCandidate">
        <el-table-column label="选择" width="64"><template #default="{ row }"><el-radio :model-value="selectedCandidate?.open_id" :label="row.open_id" @change="selectCandidate(row)"><span /></el-radio></template></el-table-column>
        <el-table-column prop="name" label="飞书姓名" min-width="120" />
        <el-table-column label="部门" min-width="140"><template #default="{ row }">{{ row.department_name || displayValue(row, 'department_names') }}</template></el-table-column>
        <el-table-column label="匹配依据" min-width="150"><template #default="{ row }"><el-tag :type="row.match_level === 'exact_contact' ? 'success' : (row.match_level === 'name_department' ? 'primary' : 'warning')">{{ row.match_reason || '人工候选' }}</el-tag></template></el-table-column>
        <el-table-column label="邮箱 / 手机" min-width="180"><template #default="{ row }"><div class="user-cell"><span>{{ row.email || '—' }}</span><span>{{ row.phone || '—' }}</span></div></template></el-table-column>
        <el-table-column prop="open_id" label="Open ID" min-width="210" />
      </el-table>
      <template #footer><el-button @click="candidateDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!selectedCandidate" @click="confirmIdentityBinding">确认绑定</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { bindFeishuIdentity, createFeishuResource, deleteFeishuResource, fetchFeishuConnection, fetchFeishuIdentityCandidates, fetchFeishuOperations, fetchFeishuResources, updateFeishuConnection, updateFeishuResource } from '../../api/feishu';

const route = useRoute(); const router = useRouter();
const auth = useAuthStore();
const tabs = [{ name: 'connection', label: '应用连接' }, { name: 'identity', label: '身份映射' }, { name: 'notification', label: '消息与预警' }, { name: 'report', label: '报表推送' }, { name: 'approval', label: '审批映射' }, { name: 'operations', label: '运行与事件' }];
const metadata = {
  identity: { resource: 'identities', title: '身份映射', singular: '身份映射', description: '系统用户全部直接展示；查询飞书候选后，由用户人工确认绑定。', createLabel: '新增映射', emptyText: '暂无可配置的系统用户。', columns: [] },
  notification: { resource: 'notifications', title: '消息与预警', singular: '通知规则', description: '为库存、经营、同步异常和审批结果配置飞书投递策略。', createLabel: '新建通知规则', emptyText: '暂无消息与预警规则。', columns: [{ prop: 'name', label: '规则名称' }, { prop: 'scene', label: '业务场景' }, { prop: 'channel', label: '投递通道' }, { prop: 'enabled', label: '状态' }] },
  report: { resource: 'reports', title: '报表推送', singular: '报表任务', description: '配置经营摘要、库存预警、补货建议等综合报表的定时推送。', createLabel: '新建报表任务', emptyText: '暂无报表推送任务。', columns: [{ prop: 'name', label: '任务名称' }, { prop: 'report_type', label: '报表类型' }, { prop: 'schedule', label: '周期' }, { prop: 'next_run_at', label: '下次运行' }, { prop: 'enabled', label: '状态' }] },
  approval: { resource: 'approvals', title: '审批映射', singular: '审批映射', description: '将采购、价格、刊登、清仓、财务和报表导出审批映射到飞书模板。', createLabel: '新建审批映射', emptyText: '暂无审批模板映射，不会向飞书发起审批。', columns: [{ prop: 'name', label: '映射名称' }, { prop: 'approval_type', label: '本地审批类型' }, { prop: 'approval_code', label: 'Approval Code' }, { prop: 'enabled', label: '状态' }] },
  operations: { resource: 'operations', title: '运行与事件', description: '查看消息投递、报表运行、审批同步和回调处理结果。', emptyText: '暂无飞书运行或事件记录。', columns: [{ prop: 'operation_type', label: '类型' }, { prop: 'business_reference', label: '业务对象' }, { prop: 'status', label: '状态' }, { prop: 'request_id', label: '请求 ID' }, { prop: 'created_at', label: '发生时间' }] }
};
const reportTypes = [{ label: '经营指标摘要', value: 'business_summary' }, { label: '库存预警汇总', value: 'inventory_alerts' }, { label: '补货建议', value: 'replenishment' }, { label: '经营预警汇总', value: 'business_alerts' }, { label: '销售明细', value: 'sales_details' }];
const approvalTypes = [{ label: '采购审批', value: 'purchase' }, { label: '价格审批', value: 'pricing' }, { label: '刊登审批', value: 'listing' }, { label: '清仓审批', value: 'clearance' }, { label: '财务审批', value: 'finance' }, { label: '报表导出审批', value: 'report_export' }];
const validTabs = new Set(tabs.map((item) => item.name));
const activeTab = ref(validTabs.has(String(route.query.tab)) ? String(route.query.tab) : 'connection');
const loading = ref(false); const saving = ref(false); const error = ref(''); const capability = ref(useMock ? 'mock' : 'pending'); const rows = ref([]); const dialogVisible = ref(false); const editingId = ref(null); const operationType = ref(''); const operationStatus = ref('');
const candidateDialogVisible = ref(false); const candidateLoading = ref(false); const candidateUserId = ref(null); const candidateSystemUser = ref(null); const candidates = ref([]); const selectedCandidate = ref(null); const candidateMessage = ref(''); const candidateMessageType = ref('info');
const connection = reactive({ app_id: '', domain: 'feishu', enabled: false, status: 'not_configured', callback_url: '', credential_configured: false, verification_token_configured: false, encrypt_key_configured: false });
const secrets = reactive({ app_secret: '', verification_token: '', encrypt_key: '' }); const editor = reactive({});
const currentMeta = computed(() => metadata[activeTab.value] || metadata.identity);
const managePermissions = { connection: 'feishu.connection.manage', identity: 'feishu.identity.manage', notification: 'feishu.notification.manage', report: 'feishu.report.manage', approval: 'feishu.approval.manage' };
const canManageCurrent = computed(() => Boolean(managePermissions[activeTab.value] && auth.hasPermission(managePermissions[activeTab.value])));
const manageHint = computed(() => canManageCurrent.value ? '' : `需要 ${managePermissions[activeTab.value] || 'feishu.view'} 权限`);
const connectionStatusLabel = computed(() => ({ connected: '已连接', active: '已连接', disabled: '已停用', error: '连接异常', not_configured: '未配置' })[connection.status] || connection.status || '未配置');
const connectionStatusType = computed(() => ({ connected: 'success', active: 'success', disabled: 'info', error: 'danger', not_configured: 'warning' })[connection.status] || 'info');

function displayValue(row, prop) { const value = row?.[prop] ?? row?.config?.[prop]; if (typeof value === 'boolean') return value ? '启用' : '停用'; if (Array.isArray(value)) return value.length ? value.join('、') : '—'; return value === null || value === undefined || value === '' ? '—' : value; }
function listRows(response) { const data = response?.data; return Array.isArray(data) ? data : (data?.items || data?.results || []); }
function setApiState(response) { capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded'); if (!response?.success) error.value = response?.message || '请求飞书集成数据失败。'; }
async function loadActive() { loading.value = true; error.value = ''; const response = activeTab.value === 'connection' ? await fetchFeishuConnection() : activeTab.value === 'operations' ? await fetchFeishuOperations({ operation_type: operationType.value || undefined, status: operationStatus.value || undefined }) : await fetchFeishuResources(currentMeta.value.resource); setApiState(response); if (response?.success) { if (activeTab.value === 'connection') Object.assign(connection, response.data || {}); else { const items = listRows(response); rows.value = activeTab.value === 'identity' ? items.map((item) => ({ ...item, ...(item.mapping || {}) })) : items; } } loading.value = false; }
function switchTab(name) { router.replace({ query: { ...route.query, tab: name === 'connection' ? undefined : name } }); loadActive(); }
async function saveConnection() { if (!canManageCurrent.value) return; saving.value = true; error.value = ''; const payload = { app_id: connection.app_id, domain: connection.domain, enabled: connection.enabled }; for (const [key, value] of Object.entries(secrets)) if (value) payload[key] = value; const response = await updateFeishuConnection(payload); setApiState(response); if (response?.success) { Object.assign(connection, response.data || {}); Object.assign(secrets, { app_secret: '', verification_token: '', encrypt_key: '' }); ElMessage.success('飞书应用连接已保存'); } saving.value = false; }
function resetEditor(row = {}) { for (const key of Object.keys(editor)) delete editor[key]; Object.assign(editor, row, { configText: JSON.stringify(row.config || {}, null, 2) }); }
function openCreate() { if (!canManageCurrent.value) return; editingId.value = null; resetEditor({ enabled: true }); dialogVisible.value = true; }
function openEdit(row) { if (!canManageCurrent.value) return; editingId.value = row.id; resetEditor({ ...row, ...(row.config || {}) }); dialogVisible.value = true; }
function stableCode() { return editor.code || `${currentMeta.value.resource}_${Date.now()}`; }
async function saveResource() { if (!canManageCurrent.value) return; let config; try { config = editor.configText?.trim() ? JSON.parse(editor.configText) : {}; } catch (_error) { ElMessage.error('规则配置必须是有效 JSON'); return; } let payload; if (activeTab.value === 'identity') { payload = { ...editor }; delete payload.configText; } else { for (const key of ['scene', 'report_type', 'schedule', 'approval_type', 'approval_code']) if (editor[key] !== undefined && editor[key] !== '') config[key] = editor[key]; payload = { name: editor.name, code: stableCode(), enabled: editor.enabled !== false, config }; } saving.value = true; const response = editingId.value ? await updateFeishuResource(currentMeta.value.resource, editingId.value, payload) : await createFeishuResource(currentMeta.value.resource, payload); setApiState(response); if (response?.success) { dialogVisible.value = false; ElMessage.success('已保存'); await loadActive(); } saving.value = false; }
async function remove(row) { if (!canManageCurrent.value) return; try { await ElMessageBox.confirm(`确定删除“${row.name || row.username || row.id}”吗？`, '删除确认', { type: 'warning' }); } catch (_error) { return; } const response = await deleteFeishuResource(currentMeta.value.resource, row.id); setApiState(response); if (response?.success) { ElMessage.success('已删除'); await loadActive(); } }
async function queryCandidates(row) { if (!canManageCurrent.value) return; const systemUserId = row.system_user_id; candidateSystemUser.value = row; candidateUserId.value = systemUserId; candidateLoading.value = true; selectedCandidate.value = null; candidates.value = []; candidateMessage.value = ''; candidateMessageType.value = 'info'; candidateDialogVisible.value = true; const response = await fetchFeishuIdentityCandidates(systemUserId); setApiState(response); if (response?.success) { candidates.value = response?.data?.candidates || []; candidateMessage.value = candidates.value.length ? `已找到 ${candidates.value.length} 个候选，请核对 Open ID 和匹配依据后绑定。` : '未找到匹配的飞书用户，请核对姓名、部门及应用通讯录可用范围。'; candidateMessageType.value = candidates.value.length ? 'success' : 'warning'; } else { candidateMessage.value = response?.message || '飞书用户查询失败，请检查通讯录权限和应用可用范围。'; candidateMessageType.value = 'error'; } candidateLoading.value = false; candidateUserId.value = null; }
function selectCandidate(row) { selectedCandidate.value = row || null; }
async function confirmIdentityBinding() { if (!canManageCurrent.value || !candidateSystemUser.value || !selectedCandidate.value) return; const candidate = selectedCandidate.value; const currentOpenId = candidateSystemUser.value.open_id; if (currentOpenId && currentOpenId !== candidate.open_id) { try { await ElMessageBox.confirm(`该系统用户当前已绑定 ${currentOpenId}，确认替换为 ${candidate.open_id}？`, '替换飞书绑定', { type: 'warning', confirmButtonText: '确认替换' }); } catch (_error) { return; } } const systemUserId = candidateSystemUser.value.system_user_id; const payload = { open_id: candidate.open_id, user_id: candidate.user_id || '', union_id: candidate.union_id || '', department_ids: candidate.department_ids || [] }; saving.value = true; const response = await bindFeishuIdentity(systemUserId, payload); setApiState(response); if (response?.success) { candidateDialogVisible.value = false; ElMessage.success(currentOpenId && currentOpenId !== candidate.open_id ? '飞书绑定已替换' : '飞书用户已绑定'); await loadActive(); } saving.value = false; }
async function unbindIdentity(row) { if (!canManageCurrent.value || !row.id) return; try { await ElMessageBox.confirm(`确认解除系统用户“${row.full_name || row.username}”与飞书用户 ${row.open_id || ''} 的绑定？不会删除任何用户。`, '解除飞书绑定', { type: 'warning', confirmButtonText: '确认解绑' }); } catch (_error) { return; } const response = await deleteFeishuResource('identities', row.id); setApiState(response); if (response?.success) { ElMessage.success('飞书绑定已解除'); await loadActive(); } }
watch(() => route.query.tab, (value) => { const next = validTabs.has(String(value)) ? String(value) : 'connection'; if (next !== activeTab.value) { activeTab.value = next; loadActive(); } });
onMounted(loadActive);
</script>

<style scoped>
.feishu-tabs { margin-bottom: 18px; }
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
@media (max-width: 720px) { .panel__header { flex-direction: column; } .form-grid { grid-template-columns: 1fr; } }
</style>
