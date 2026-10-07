<template>
  <el-drawer v-model="open" title="授权工作台" size="min(1080px, 96vw)" @open="loadUsers">
    <p class="workbench-intro">集中处理人员调动与离职，先预览变更，再确认提交。</p><el-tabs v-model="activeTab"><el-tab-pane label="批量授权" name="batch"><div class="workbench-steps"><span :class="{active: !previewData}">1 · 选择人员与调整内容</span><span :class="{active: previewData}">2 · 核对变更并提交</span></div>
    <div class="workbench-controls">
      <el-select v-model="operation" aria-label="操作类型"><el-option label="岗位/角色调动" value="transfer"/><el-option label="离职收回角色" value="offboard"/></el-select>
      <el-select v-model="roleCodes" multiple filterable placeholder="选择调入角色" :disabled="operation === 'offboard' || loadingRoles"><el-option v-for="role in roles" :key="role.code" :label="adminRoleDisplayName(role)" :value="role.code"/></el-select>
      <el-select v-model="replaceSource" aria-label="替换来源"><el-option label="替换旧版租户绑定（其他来源保留）" value="legacy"/><el-option label="替换岗位来源绑定（其他来源保留）" value="position"/></el-select>
      <el-input v-model="reason" maxlength="500" placeholder="操作原因（必填）" />
    </div>
    <el-table :data="users" v-loading="loadingUsers" @selection-change="selected = $event" max-height="280">
      <el-table-column type="selection" width="48"/><el-table-column prop="username" label="用户名"/><el-table-column prop="full_name" label="姓名"/><el-table-column label="当前角色"><template #default="{row}">{{ formatRoleCodes(row.roles) }}</template></el-table-column>
    </el-table>
    <div class="actions"><el-button :loading="previewing" :disabled="!selected.length || !reason.trim() || (operation === 'transfer' && !roleCodes.length) || auth.authorizationStale" @click="preview">生成预览</el-button><el-button type="danger" :loading="applying" :disabled="!canApply" @click="apply">确认提交</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="previewData">
      <el-alert v-if="previewData.warnings?.length" :title="previewData.warnings.join('；')" type="warning" :closable="false" show-icon />
      <el-table :data="previewData.changes || []" border><el-table-column prop="username" label="用户"/><el-table-column label="变更前角色"><template #default="{row}">{{ formatRoleCodes(row.before_roles) }}</template></el-table-column><el-table-column v-for="change in permissionChangeColumns" :key="change.prop" :label="change.label"><template #default="{row}"><el-popover v-if="row[change.prop]?.length" trigger="click" :width="360" :title="change.label"><template #reference><el-button link type="primary">查看 {{ row[change.prop].length }} 项</el-button></template><div class="preview-permissions"><p v-for="code in row[change.prop]" :key="code">{{ adminPermissionLabel(code) }}</p></div></el-popover><span v-else>无</span></template></el-table-column><el-table-column label="变更后角色"><template #default="{row}">{{ formatRoleCodes(row.after_roles) }}</template></el-table-column></el-table>
    </template>
    </el-tab-pane><el-tab-pane label="有效权限与模拟" name="inspect">
    <div class="workbench-controls"><el-select v-model="inspectUser" filterable placeholder="选择用户" @change="loadEffective"><el-option v-for="user in users" :key="user.id" :label="user.username" :value="user.id"/></el-select><el-input v-model="permissionCode" placeholder="权限编码，例如 inventory.view"/><el-button @click="simulate">模拟检查</el-button></div>
    <el-alert v-if="simulation" :title="simulation.allowed ? '模拟结果：允许' : `模拟结果：拒绝（${simulationReasonLabel(simulation.reason)}）`" :description="`范围：${formatScope(simulation.scopes)}；来源：${formatSources(simulation.sources)}`" :type="simulation.allowed ? 'success' : 'warning'" :closable="false" />
    <EffectivePermissionsPanel v-if="inspectUser" :permissions="effective?.permissions || []" :roles="roles" :loading="loadingEffective"/>
    <el-alert v-if="effective?.offboarding_checklist" title="离职核对" :description="formatChecklist(effective.offboarding_checklist) + '；共享凭据需人工跟进，不会删除。'" type="info" :closable="false" />
    </el-tab-pane></el-tabs>
    <template #footer><el-button @click="open = false">关闭</el-button></template>
  </el-drawer>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import EffectivePermissionsPanel from './EffectivePermissionsPanel.vue';
import { adminPermissionLabel, adminRoleDisplayName } from '../../utils/adminDisplayLabels';
import { effectivePermissionSourceLabels } from '../../utils/effectivePermissionDisplay';
import { createRequestSequence } from '../../utils/asyncRequestControl';
import { useAuthStore } from '../../stores/auth';
import { authorizationPreviewSignature, canApplyAuthorizationPreview } from '../../utils/authorizationPreview';
import { fetchAssignableRoles, fetchUsers } from '../../api/systemAdmin';
import { applyAuthorizationBatch, fetchEffectivePermissions, previewAuthorizationBatch, simulateAuthorization } from '../../api/authorization';
const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'saved']);
const open = ref(props.modelValue), activeTab = ref('batch'), loadingEffective = ref(false);
watch(() => props.modelValue, value => { open.value = value; });
watch(open, value => emit('update:modelValue', value));
const auth = useAuthStore();
const users = ref([]), selected = ref([]), roles = ref([]), roleCodes = ref([]), replaceSource = ref('position'), operation = ref('transfer');
const loadingUsers = ref(false), loadingRoles = ref(false), previewing = ref(false), applying = ref(false), error = ref('');
const reason = ref(''), previewData = ref(null), inspectUser = ref(null), effective = ref(null), permissionCode = ref(''), simulation = ref(null);
const previewSignature = ref('');
const permissionChangeColumns = [{ prop: 'added', label: '新增权限' }, { prop: 'removed', label: '收回权限' }, { prop: 'retained', label: '保留权限' }];
const effectiveLoads = createRequestSequence();
watch(open, value => { if (!value) effectiveLoads.begin(); });
const inputSignature = computed(() => authorizationPreviewSignature({ userIds: selected.value.map(user => user.id), roleCodes: roleCodes.value, operation: operation.value, replaceSource: replaceSource.value, reason: reason.value }));
const canApply = computed(() => canApplyAuthorizationPreview(previewData.value, previewSignature.value, inputSignature.value, auth.authorizationStale));
watch(inputSignature, () => { previewData.value = null; previewSignature.value = ''; });
async function loadUsers() {
  loadingUsers.value = true; loadingRoles.value = true; error.value = '';
  const loadPages = async (loader) => {
    const rows = []; let page = 1; let first = null;
    while (page <= 1000) {
      const response = await loader({ page, page_size: 100 });
      first ||= response;
      if (!response?.success) return { response, rows: [] };
      rows.push(...(response.data?.results || response.data?.items || []));
      const count = Number(response.data?.count);
      if (!response.data?.next || (Number.isFinite(count) && rows.length >= count)) break;
      page += 1;
    }
    return { response: first, rows };
  };
  const [u, r] = await Promise.all([loadPages(fetchUsers), loadPages(fetchAssignableRoles)]);
  loadingUsers.value = false; loadingRoles.value = false;
  if (!u.response?.success) error.value = u.response?.message || '用户加载失败'; else users.value = u.rows;
  if (r.response?.success) roles.value = r.rows; else ElMessage.error(r.response?.message || '角色加载失败');
}
async function preview() {
  if (auth.authorizationStale || !auth.hasPermission('system.users.manage')) { error.value = '当前授权状态无效或缺少用户管理权限，无法生成预览。'; return; }
  previewing.value = true; error.value = ''; previewData.value = null; previewSignature.value = '';
  const signature = inputSignature.value;
  const response = await previewAuthorizationBatch({ user_ids: selected.value.map(u => u.id), role_codes: operation.value === 'offboard' ? [] : roleCodes.value, replace_source: replaceSource.value, reason: reason.value.trim(), operation: operation.value });
  previewing.value = false;
  if (!response?.success) { error.value = response?.http_status === 409 ? '授权版本已变化，请刷新用户并重新生成预览。' : response?.message || '预览失败'; return; }
  if (signature !== inputSignature.value) { error.value = '预览期间表单内容发生变化，请重新生成预览。'; return; }
  previewData.value = response.data; previewSignature.value = signature;
}
async function apply() {
  if (!canApply.value || !auth.hasPermission('system.users.manage')) return;
  applying.value = true; const response = await applyAuthorizationBatch(previewData.value.preview_token); applying.value = false;
  if (!response?.success) { error.value = response?.http_status === 409 ? '预览已过期或版本冲突，请重新生成预览。' : response?.message || '提交失败'; previewData.value = null; return; }
  const refreshed = await auth.refreshCurrentUser();
  ElMessage.success('批量授权已提交'); previewData.value = null; previewSignature.value = ''; selected.value = []; await loadUsers(); emit('saved', response.data);
  if (!refreshed?.success) error.value = '批量操作已完成，但当前会话权限刷新失败；敏感操作已暂停。';
}
async function loadEffective() { const loadToken = effectiveLoads.begin(), userId = inspectUser.value; loadingEffective.value=true; effective.value=null; simulation.value=null; const r = await fetchEffectivePermissions(userId); if (!loadToken.isCurrent() || inspectUser.value !== userId) return; loadingEffective.value=false; effective.value = r?.success ? r.data : null; if (!r?.success) error.value = r?.message || '有效权限加载失败'; }
async function simulate() { if (auth.authorizationStale || !auth.hasPermission('system.users.manage') || !inspectUser.value || !permissionCode.value.trim()) return; const userId=inspectUser.value, code=permissionCode.value.trim(); const r = await simulateAuthorization({ user_id: userId, permission_code: code }); if (inspectUser.value !== userId || permissionCode.value.trim() !== code) return; simulation.value = r?.success ? r.data : null; if (!r?.success) error.value = r?.message || '授权模拟失败'; }
const dimensionLabels = { platform_ids: '平台', site_ids: '站点', store_ids: '店铺', warehouse_ids: '仓库', supplier_ids: '供应商' };
function formatScope(scopes) {
  if (!scopes?.length) return '未返回范围';
  return scopes.map(scope => {
    if (typeof scope === 'string') return scope === 'all' ? '租户全部范围' : scope;
    if (scope.scope_type === 'all') return '租户全部范围';
    return Object.entries(scope.config || scope).map(([key, values]) => `${dimensionLabels[key] || key}：${Array.isArray(values) ? values.join('、') : values}`).join('；') || (scope.scope_type === 'all' ? '租户全部范围' : '自定义范围');
  }).join('；');
}
function formatSources(sources) {
  if (!sources?.length) return '无匹配来源';
  return effectivePermissionSourceLabels({sources},roles.value).join('、') || '无匹配来源';
}
function formatRoleCodes(codes) { return (codes || []).map(code=>adminRoleDisplayName(roles.value.find(role=>role.code===code) || {code})).join('、') || '无角色'; }
function simulationReasonLabel(reason) { return ({permission_granted:'匹配有效授权',no_matching_grant:'无匹配授权',permission_denied:'无匹配授权',permission_inactive:'权限已停用',user_inactive:'账号已停用',tenant_mismatch:'租户不匹配',scope_mismatch:'超出数据范围',no_grants:'无有效授权'})[reason] || '未匹配有效授权'; }
const checklistLabels = { account: '账号', tokens: '访问令牌', bindings: '角色绑定', export: '数据导出', shared_credentials: '共享凭据' };
function formatChecklist(checklist) {
  if (Array.isArray(checklist)) return checklist.map(item => `${item.item || '待办事项'}：${({ active: '当前有效', blocked: '已停用', revoke_on_offboard: '离职时收回', download_rechecked_and_blocked: '下载时重新校验并阻止', requires_current_actor_recheck: '需由当前操作者重新校验', manual_owner_review_no_shared_credentials_deleted: '需人工确认凭据归属，系统不会删除共享凭据' })[item.status] || item.status || '待核对'}`).join('；') || '暂无待办项';
  return Object.entries(checklist || {}).map(([key, value]) => `${checklistLabels[key] || key}：${typeof value === 'boolean' ? (value ? '需处理' : '无需处理') : Array.isArray(value) ? value.join('、') : String(value)}`).join('；') || '暂无待办项';
}
</script>
<style scoped>.workbench-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0}.actions{display:flex;justify-content:flex-end;gap:8px;margin:12px 0}h3{font-size:15px;color:#334155}.workbench-intro{margin:0 0 20px;color:#73839a;font-size:14px}.workbench-steps{display:flex;gap:20px;color:#8a99af;font-size:13px;padding:16px 0;border-bottom:1px solid #e4eaf3}.workbench-steps .active{color:#2463eb;font-weight:600}@media(max-width:640px){.workbench-controls{grid-template-columns:1fr}.workbench-steps{gap:12px;flex-wrap:wrap}}
</style>
<style scoped>.preview-permissions{max-height:280px;overflow-y:auto;font-size:13px;line-height:1.6}.preview-permissions p{padding:6px 0;margin:0;border-bottom:1px solid #edf1f6}</style>
