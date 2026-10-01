<template>
  <el-drawer v-model="open" title="授权工作台" size="min(900px, 96vw)" @open="loadUsers">
    <el-alert title="批量变更必须先生成预览，再明确提交。预览令牌十分钟有效；版本冲突时请重新预览。离职处理不会删除共享凭据。" type="warning" :closable="false" show-icon />
    <div class="workbench-controls">
      <el-select v-model="operation" aria-label="操作类型"><el-option label="岗位/角色调动" value="transfer"/><el-option label="离职收回角色" value="offboard"/></el-select>
      <el-select v-model="roleCodes" multiple filterable placeholder="选择调入角色" :disabled="operation === 'offboard' || loadingRoles"><el-option v-for="role in roles" :key="role.code" :label="role.name || role.code" :value="role.code"/></el-select>
      <el-select v-model="replaceSource" aria-label="替换来源"><el-option label="替换旧版租户绑定（其他来源保留）" value="legacy"/><el-option label="替换岗位来源绑定（其他来源保留）" value="position"/></el-select>
      <el-input v-model="reason" maxlength="500" placeholder="操作原因（必填）" />
    </div>
    <el-table :data="users" v-loading="loadingUsers" @selection-change="selected = $event" max-height="280">
      <el-table-column type="selection" width="48"/><el-table-column prop="username" label="用户名"/><el-table-column prop="full_name" label="姓名"/><el-table-column label="当前角色"><template #default="{row}">{{ (row.roles || []).join('、') || '—' }}</template></el-table-column>
    </el-table>
    <div class="actions"><el-button :loading="previewing" :disabled="!selected.length || !reason.trim() || (operation === 'transfer' && !roleCodes.length) || auth.authorizationStale" @click="preview">生成预览</el-button><el-button type="danger" :loading="applying" :disabled="!canApply" @click="apply">确认提交</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="previewData">
      <el-alert v-if="previewData.warnings?.length" :title="previewData.warnings.join('；')" type="warning" :closable="false" show-icon />
      <el-table :data="previewData.changes || []" border><el-table-column prop="username" label="用户"/><el-table-column label="变更前"><template #default="{row}">{{ (row.before_roles || []).join('、') || '无角色' }}</template></el-table-column><el-table-column label="增加"><template #default="{row}">{{ (row.added || []).join('、') || '—' }}</template></el-table-column><el-table-column label="移除"><template #default="{row}">{{ (row.removed || []).join('、') || '—' }}</template></el-table-column><el-table-column label="保留"><template #default="{row}">{{ (row.retained || []).join('、') || '—' }}</template></el-table-column><el-table-column label="变更后"><template #default="{row}">{{ (row.after_roles || []).join('、') || '无角色' }}</template></el-table-column></el-table>
    </template>
    <el-divider />
    <h3>有效权限与授权模拟</h3>
    <div class="workbench-controls"><el-select v-model="inspectUser" filterable placeholder="选择用户" @change="loadEffective"><el-option v-for="user in users" :key="user.id" :label="user.username" :value="user.id"/></el-select><el-input v-model="permissionCode" placeholder="权限编码，例如 inventory.view"/><el-button @click="simulate">模拟检查</el-button></div>
    <el-alert v-if="simulation" :title="simulation.allowed ? '模拟结果：允许' : `模拟结果：拒绝（${simulation.reason || '无匹配授权'}）`" :description="`范围：${formatScope(simulation.scopes)}；来源：${formatSources(simulation.sources)}`" :type="simulation.allowed ? 'success' : 'warning'" :closable="false" />
    <el-table v-if="effective" :data="effective.permissions || []" max-height="240"><el-table-column prop="code" label="权限"/><el-table-column prop="permission_type" label="类型"/><el-table-column label="结果"><template #default="{row}">{{ row.allowed ? '允许' : '拒绝' }}</template></el-table-column><el-table-column label="来源"><template #default="{row}">{{ formatSources(row.sources) }}</template></el-table-column></el-table>
    <el-alert v-if="effective?.offboarding_checklist" title="离职核对" :description="formatChecklist(effective.offboarding_checklist) + '；共享凭据需人工跟进，不会删除。'" type="info" :closable="false" />
  </el-drawer>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { authorizationPreviewSignature, canApplyAuthorizationPreview } from '../../utils/authorizationPreview';
import { fetchAssignableRoles, fetchUsers } from '../../api/systemAdmin';
import { applyAuthorizationBatch, fetchEffectivePermissions, previewAuthorizationBatch, simulateAuthorization } from '../../api/authorization';
const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'saved']);
const open = ref(false);
watch(() => props.modelValue, value => { open.value = value; });
watch(open, value => emit('update:modelValue', value));
const auth = useAuthStore();
const users = ref([]), selected = ref([]), roles = ref([]), roleCodes = ref([]), replaceSource = ref('position'), operation = ref('transfer');
const loadingUsers = ref(false), loadingRoles = ref(false), previewing = ref(false), applying = ref(false), error = ref('');
const reason = ref(''), previewData = ref(null), inspectUser = ref(null), effective = ref(null), permissionCode = ref(''), simulation = ref(null);
const previewSignature = ref('');
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
async function loadEffective() { const r = await fetchEffectivePermissions(inspectUser.value); effective.value = r?.success ? r.data : null; if (!r?.success) error.value = r?.message || '有效权限加载失败'; }
async function simulate() { if (auth.authorizationStale || !auth.hasPermission('system.users.manage') || !inspectUser.value || !permissionCode.value.trim()) return; const r = await simulateAuthorization({ user_id: inspectUser.value, permission_code: permissionCode.value.trim() }); simulation.value = r?.success ? r.data : null; if (!r?.success) error.value = r?.message || '授权模拟失败'; }
const dimensionLabels = { platform_ids: '平台', site_ids: '站点', store_ids: '店铺', warehouse_ids: '仓库', supplier_ids: '供应商' };
function formatScope(scopes) {
  if (!scopes?.length) return '未返回范围';
  return scopes.map(scope => {
    if (typeof scope === 'string') return scope === 'all' ? '租户全部范围' : scope;
    return Object.entries(scope.config || scope).map(([key, values]) => `${dimensionLabels[key] || key}：${Array.isArray(values) ? values.join('、') : values}`).join('；') || (scope.scope_type === 'all' ? '租户全部范围' : '自定义范围');
  }).join('；');
}
function formatSources(sources) {
  if (!sources?.length) return '无匹配来源';
  return sources.map(source => [source.role_code || source.source || '授权来源', source.scope ? formatScope(Array.isArray(source.scope) ? source.scope : [source.scope]) : '', source.valid_until ? `有效至 ${source.valid_until}` : ''].filter(Boolean).join('，')).join('；');
}
const checklistLabels = { account: '账号', tokens: '访问令牌', bindings: '角色绑定', export: '数据导出', shared_credentials: '共享凭据' };
function formatChecklist(checklist) {
  if (Array.isArray(checklist)) return checklist.map(item => `${item.item || '待办事项'}：${({ active: '当前有效', blocked: '已停用', revoke_on_offboard: '离职时收回', download_rechecked_and_blocked: '下载时重新校验并阻止', requires_current_actor_recheck: '需由当前操作者重新校验', manual_owner_review_no_shared_credentials_deleted: '需人工确认凭据归属，系统不会删除共享凭据' })[item.status] || item.status || '待核对'}`).join('；') || '暂无待办项';
  return Object.entries(checklist || {}).map(([key, value]) => `${checklistLabels[key] || key}：${typeof value === 'boolean' ? (value ? '需处理' : '无需处理') : Array.isArray(value) ? value.join('、') : String(value)}`).join('；') || '暂无待办项';
}
</script>
<style scoped>.workbench-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0}.actions{display:flex;justify-content:flex-end;gap:8px;margin:12px 0}h3{font-size:15px;color:#334155}</style>
