<template>
  <AdminResourcePage
    ref="resourcePage"
    title="用户目录"
    subtitle="管理人员、部门与角色，维护账号状态和部门归属。"
    entity-label="用户"
    :loader="fetchUsers"
    :external-filters="departmentFilters"
    :columns="columns"
    :detail-columns="detailColumns"
    :form-fields="formFields"
    :create-handler="createUser"
    :before-create="prepareCreateForm"
    :edit-handler="handleUserEdit"
    :delete-handler="deleteUser"
    :status-handler="handleStatus"
    create-permission="system.users.manage"
    manage-permission="system.users.manage"
    :operation-width="220"
    :compact-actions="true"
    :show-summary="false"
    search-label="姓名或账号"
  >
    <template #sidebar>
      <DepartmentTree
        v-if="departmentTreeVisible"
        :nodes="treeNodes"
        :loading="treeLoading"
        :error-message="treeError"
        :can-manage="false"
        :show-all="true"
        :all-selected="allUsersSelected"
        :show-unassigned="true"
        :unassigned-selected="departmentFilters.unassigned"
        :selected-id="departmentFilters.department_id"
        @select="selectDepartment"
        @select-all="selectAllUsers"
        @select-unassigned="selectUnassigned"
      />
      <el-alert
        v-else
        :title="departmentFieldVisible
          ? '当前角色没有组织查看权限，组织筛选树未加载；部门调整仍需用户管理权限。'
          : '当前角色没有部门字段权限，组织筛选和部门调整入口已隐藏。'"
        type="info"
        :closable="false"
        show-icon
      />
      <section v-if="departmentTreeVisible && departmentFilters.department_id" class="directory-scope">
        <strong>部门筛选范围</strong>
        <el-radio-group v-model="departmentFilters.include_descendants" @change="reloadUsers">
          <el-radio-button :value="false">仅直属</el-radio-button>
          <el-radio-button :value="true">包含下级</el-radio-button>
        </el-radio-group>
        <small>兼任部门人员按任一部门匹配；数据范围仍由后端最终校验。</small>
      </section>
    </template>
    <template #header-actions>
      <el-tag effect="plain">{{ filterSummary }}</el-tag>
      <el-button v-if="roleAccess.visible" type="primary" plain :disabled="roleAccess.disabled" @click="authorizationWorkbenchOpen = true">授权工作台</el-button>
    </template>
    <template #row-actions="{ row, edit, remove, toggleStatus }">
      <el-button v-if="roleAccess.visible" link type="primary" :disabled="roleAccess.disabled" @click.stop="openRoleAssignment(row)">分配角色</el-button>
      <el-dropdown trigger="click" @command="command => handleRowCommand(command, row, { edit, remove, toggleStatus })"><el-button link type="primary" @click.stop>更多<el-icon class="more-arrow"><ArrowDown/></el-icon></el-button><template #dropdown><el-dropdown-menu>
        <el-dropdown-item v-if="roleAccess.visible" command="edit" :disabled="roleAccess.disabled">编辑资料</el-dropdown-item>
        <el-dropdown-item v-if="departmentAccess.visible && departmentFieldVisible" command="department" :disabled="departmentAccess.disabled">调整部门</el-dropdown-item>
        <el-dropdown-item v-if="roleAccess.visible" command="effective" :disabled="roleAccess.disabled">查看有效权限</el-dropdown-item>
        <el-dropdown-item v-if="roleAccess.visible" command="password" :disabled="roleAccess.disabled">重置密码</el-dropdown-item>
        <el-dropdown-item v-if="roleAccess.visible" command="status" :disabled="roleAccess.disabled" divided>{{ row.is_active ? '停用账号' : '启用账号' }}</el-dropdown-item>
        <el-dropdown-item v-if="roleAccess.visible" command="delete" :disabled="roleAccess.disabled" class="danger-action">删除账号</el-dropdown-item>
      </el-dropdown-menu></template></el-dropdown>
    </template>
  </AdminResourcePage>

  <el-dialog v-model="departmentDialogOpen" title="调整部门归属" width="min(560px, 94vw)">
    <p class="role-user">用户：<strong>{{ selectedUser.username }}</strong></p>
    <el-alert
      title="主部门用于 department_tree 数据范围锚定；兼任部门只增加组织归属，不改变主部门。"
      type="info"
      :closable="false"
      show-icon
    />
    <el-form label-position="top" class="department-form">
      <el-form-item label="主部门">
        <el-select v-model="selectedDepartmentId" clearable filterable placeholder="未分配主部门" style="width: 100%">
          <el-option v-for="item in departmentOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="兼任部门">
        <el-select
          v-model="selectedDepartmentIds"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="可多选兼任部门"
          style="width: 100%"
        >
          <el-option v-for="item in departmentOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="departmentDialogOpen = false">取消</el-button>
      <el-button
        type="primary"
        :loading="departmentSaving"
        :disabled="departmentAccess.disabled"
        @click="saveDepartmentAssignment"
      >保存部门</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="passwordDialogOpen" title="重置用户密码" width="min(480px, 94vw)" destroy-on-close>
    <p class="role-user">用户：<strong>{{ selectedUser.username }}</strong></p>
    <el-alert title="新密码至少12位，提交后不会回显；操作会写入审计日志。" type="warning" :closable="false" show-icon />
    <el-form label-position="top" class="password-form" @submit.prevent="savePasswordReset">
      <el-form-item label="新密码" required><el-input v-model="passwordForm.new_password" type="password" show-password autocomplete="new-password" placeholder="至少12位" /></el-form-item>
      <el-form-item label="确认新密码" required><el-input v-model="passwordForm.confirm_password" type="password" show-password autocomplete="new-password" placeholder="再次输入新密码" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="passwordDialogOpen = false">取消</el-button>
      <el-button type="primary" :loading="passwordSaving" :disabled="roleAccess.disabled" @click="savePasswordReset">保存密码</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="roleDialogOpen" title="分配用户角色" width="min(520px, 94vw)">
    <p class="role-user">用户：<strong>{{ selectedUser.username }}</strong></p>
    <el-form label-position="top">
      <el-form-item label="角色">
        <el-select
          v-model="selectedRoleCodes"
          multiple
          filterable
          :loading="roleOptionsLoading"
          placeholder="选择当前租户的角色"
          style="width: 100%"
        >
          <el-option
            v-for="role in roleSelectOptions"
            :key="role.code"
            :label="adminRoleDisplayName(role)"
            :value="role.code"
          />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="roleDialogOpen = false">取消</el-button>
      <el-button type="primary" :loading="roleSaving" @click="saveRoleAssignment">保存角色</el-button>
    </template>
  </el-dialog>

  <AuthorizationWorkbench v-model="authorizationWorkbenchOpen" @saved="refreshAuthorizationView" />
  <el-drawer v-model="effectiveDrawerOpen" :title="`用户有效权限 / ${selectedUser.full_name || selectedUser.username || ''}`" size="min(1080px, 96vw)" class="effective-drawer" destroy-on-close>
    <p class="effective-subtitle">查看当前生效的权限与授权来源。</p><el-alert v-if="effectiveError" :title="effectiveError" type="error" :closable="false" show-icon />
    <el-tabs v-model="effectiveTab"><el-tab-pane label="有效权限" name="permissions"><EffectivePermissionsPanel :permissions="effectiveData?.permissions || []" :roles="roleOptions" :loading="effectiveLoading"/></el-tab-pane><el-tab-pane label="组织岗位" name="organization"><section class="organization-workspace">    <el-alert v-if="organizationError" :title="organizationError" type="error" :closable="false" show-icon />
    <el-alert v-if="!departmentFieldVisible" title="当前账号没有部门字段查看权限，组织岗位编辑已关闭。" type="warning" :closable="false" />
    <el-alert v-if="organizationData" title="保存只更新所选部门的岗位来源绑定；其他部门、旧版租户来源和其他授权来源保持原样。" type="info" :closable="false" />
    <el-table v-if="organizationData" :data="selectedOrganizationMembership ? [selectedOrganizationMembership] : []" v-loading="organizationLoading" size="small">
      <el-table-column label="部门"><template #default="{row}">{{ departmentLabel(row.department_id) }}</template></el-table-column><el-table-column label="成员状态"><template #default="{row}">{{ adminStatusLabel(row.status) }}</template></el-table-column><el-table-column prop="valid_until" label="成员有效期"/>
    </el-table>
    <el-table v-if="organizationData" :data="selectedOrganizationBindings" size="small">
      <el-table-column label="岗位角色"><template #default="{row}">{{ roleName(row) }}</template></el-table-column><el-table-column label="状态"><template #default="{row}">{{ adminStatusLabel(row.status) }}</template></el-table-column><el-table-column prop="valid_until" label="绑定有效期"/>
    </el-table>
    <el-table v-if="unmodifiedOrganizationBindings.length" :data="unmodifiedOrganizationBindings" size="small">
      <el-table-column label="保留的其他绑定"><template #default="{row}">{{ roleName(row) }}（{{ organizationSourceLabel(row.source) }}）</template></el-table-column><el-table-column prop="membership_id" label="组织成员"/><el-table-column prop="valid_until" label="有效期"/>
    </el-table>
    <el-form v-if="organizationData" label-position="top" class="org-form">
      <el-form-item label="部门"><el-select v-model="organizationForm.department_id" :disabled="!departmentFieldVisible" clearable filterable placeholder="选择部门" style="width:100%"><el-option v-for="item in departmentOptions" :key="item.value" :label="item.label" :value="item.value"/></el-select></el-form-item>
      <el-form-item label="岗位角色"><el-select v-model="organizationForm.role_codes" multiple filterable placeholder="选择组织岗位角色" style="width:100%"><el-option v-for="item in roleOptions" :key="item.code" :label="adminRoleDisplayName(item)" :value="item.code"/></el-select></el-form-item>
      <el-form-item label="成员状态"><el-select v-model="organizationForm.status"><el-option label="有效" value="active"/><el-option label="停用" value="inactive"/></el-select></el-form-item>
      <el-form-item label="到期时间（可选）"><el-input v-model="organizationForm.valid_until" type="datetime-local"/></el-form-item>
      <el-button type="primary" :loading="organizationSaving" :disabled="!roleAccess.allowed || !departmentFieldVisible || organizationLoading || !organizationData" @click="saveOrganization">保存组织岗位</el-button>
    </el-form>
</section></el-tab-pane>
      <el-tab-pane label="授权模拟" name="simulation"><section class="simulation-workspace"><h3>检查指定权限</h3><p>选择权限后查看授权结果、数据范围和来源。</p><el-select v-model="simulateCode" filterable allow-create default-first-option placeholder="搜索或输入权限编码" aria-label="模拟权限"><el-option v-for="permission in effectiveData?.permissions || []" :key="permission.code" :label="adminPermissionLabel(permission.code)" :value="permission.code"/></el-select><el-button type="primary" :loading="simulating" :disabled="auth.authorizationStale || !roleAccess.allowed || !simulateCode.trim()" @click="runSimulation">模拟检查</el-button><el-alert v-if="simulationResult" :title="simulationResult.allowed ? '允许' : '拒绝：' + simulationReasonLabel(simulationResult.reason)" :description="`范围：${formatScope(simulationResult.scopes)}；来源：${formatSources(simulationResult.sources)}`" :type="simulationResult.allowed ? 'success' : 'warning'" :closable="false"/></section></el-tab-pane>
      <el-tab-pane label="离职核对" name="checklist"><el-alert v-if="effectiveData?.offboarding_checklist" title="离职核对清单" :description="formatChecklist(effectiveData.offboarding_checklist) + '。共享凭据请人工跟进。'" type="warning" :closable="false" show-icon/><el-empty v-else description="暂无核对清单"/></el-tab-pane></el-tabs>
    <template #footer><el-button @click="effectiveDrawerOpen = false">关闭</el-button></template>
  </el-drawer>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { ArrowDown } from '@element-plus/icons-vue';
import EffectivePermissionsPanel from '../../components/system/EffectivePermissionsPanel.vue';
import { effectivePermissionSourceLabels } from '../../utils/effectivePermissionDisplay';
import { createRequestSequence } from '../../utils/asyncRequestControl';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import DepartmentTree from '../../components/DepartmentTree.vue';
import AuthorizationWorkbench from '../../components/system/AuthorizationWorkbench.vue';
import { fetchEffectivePermissions, fetchOrganizationBindings, saveOrganizationBindings, simulateAuthorization } from '../../api/authorization';
import {
  createUser, fetchAssignableRoles, fetchDepartmentTree, fetchUsers,
  updateUserDepartments, updateUserRoles, updateUserStatus, updateUserProfile,
  resetUserPassword, deleteUser
} from '../../api/systemAdmin';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { adminRoleDisplayName, departmentDisplayName, adminPermissionLabel, adminStatusLabel } from '../../utils/adminDisplayLabels';

const auth = useAuthStore();
const resourcePage = ref(null);
const authorizationWorkbenchOpen = ref(false);
const effectiveDrawerOpen = ref(false);
const effectiveTab = ref('permissions');
const effectiveLoading = ref(false);
const effectiveError = ref('');
const effectiveData = ref(null);
const effectiveLoads = createRequestSequence();
const simulationLoads = createRequestSequence();
watch(effectiveDrawerOpen, open => { if (!open) { effectiveLoads.begin(); simulationLoads.begin(); } });
const simulateCode = ref('');
const simulating = ref(false);
const simulationResult = ref(null);
const organizationData = ref(null);
const organizationLoading = ref(false);
const organizationSaving = ref(false);
const organizationError = ref('');
const organizationForm = reactive({ department_id: null, role_codes: [], status: 'active', valid_until: '' });
let organizationLoadSequence = 0;
let suppressDepartmentReload = false;
const treeNodes = ref([]);
const treeLoading = ref(true);
const treeError = ref('');
const departmentDialogOpen = ref(false);
const departmentSaving = ref(false);
const roleDialogOpen = ref(false);
const roleOptionsLoading = ref(false);
const roleSaving = ref(false);
const passwordDialogOpen = ref(false);
const passwordSaving = ref(false);
const passwordForm = reactive({ new_password: '', confirm_password: '' });
const roleOptions = ref([]);
const selectedRoleCodes = ref([]);
const selectedDepartmentId = ref(null);
const selectedDepartmentIds = ref([]);
const selectedUser = ref({});
const departmentFilters = reactive({
  department_id: undefined,
  include_descendants: false,
  unassigned: false,
});

const roleAccess = computed(() => getActionAccess(auth, { permission: 'system.users.manage' }));
const departmentAccess = computed(() => getActionAccess(auth, { permission: 'system.users.manage' }));
const departmentFieldVisible = computed(() => auth.hasFieldPermission('field.system.users.department.view'));
const organizationViewAllowed = computed(() => auth.hasPermission('system.organization.view'));
const departmentTreeVisible = computed(() => departmentFieldVisible.value && organizationViewAllowed.value);
const allUsersSelected = computed(() => (
  !departmentFilters.department_id && !departmentFilters.unassigned && !departmentFilters.include_descendants
));
const roleSelectOptions = computed(() => {
  const options = new Map(roleOptions.value.map((role) => [role.code, role]));
  const assignedCodes = selectedUser.value?.roles || [];
  const assignedNames = selectedUser.value?.role_labels || [];
  assignedCodes.forEach((code, index) => {
    if (!options.has(code)) options.set(code, { code, name: assignedNames[index] || code });
  });
  return [...options.values()];
});
const filterSummary = computed(() => {
  if (departmentFilters.unassigned) return '未分配人员';
  if (!departmentFilters.department_id) return '全部可见用户';
  return departmentFilters.include_descendants ? '当前部门及下级' : '当前部门直属';
});
const selectedOrganizationMembership = computed(() => {
  const memberships = organizationData.value?.memberships || [];
  const scoped = memberships.filter(membership => String(membership.department_id) === String(organizationForm.department_id));
  return scoped.find(membership => membership.status === 'active') || scoped[0] || null;
});
const selectedOrganizationBindings = computed(() => {
  const membershipId = selectedOrganizationMembership.value?.id;
  if (membershipId == null) return [];
  return (organizationData.value?.bindings || []).filter(binding => (
    String(binding.membership_id) === String(membershipId) && binding.source === 'position'
  ));
});
const unmodifiedOrganizationBindings = computed(() => {
  const membershipId = selectedOrganizationMembership.value?.id;
  if (membershipId == null) return organizationData.value?.bindings || [];
  return (organizationData.value?.bindings || []).filter(binding => (
    !(String(binding.membership_id) === String(membershipId) && binding.source === 'position')
  ));
});
function roleName(binding) { const role=roleOptions.value.find(role=>role.code===binding.role_code || String(role.id)===String(binding.role_id)); return role ? adminRoleDisplayName(role) : adminRoleDisplayName({code:binding.role_code,id:binding.role_id}); }
function organizationSourceLabel(source) { return ({position:'组织岗位',legacy:'旧版租户授权',direct:'直接授权',manual:'人工授权'})[source] || '其他授权来源'; }
function simulationReasonLabel(reason) { return ({permission_granted:'匹配有效授权',no_matching_grant:'无匹配授权',permission_denied:'无匹配授权',permission_inactive:'权限已停用',user_inactive:'账号已停用',tenant_mismatch:'租户不匹配',scope_mismatch:'超出数据范围',no_grants:'无有效授权'})[reason] || '未匹配有效授权'; }
function handleRowCommand(command,row,actions) { if (!roleAccess.value.allowed) return; const handlers={edit:actions.edit,delete:actions.remove,status:actions.toggleStatus,department:()=>openDepartmentDialog(row),effective:()=>openEffectivePermissions(row),password:()=>openPasswordReset(row)}; handlers[command]?.(); }

function departmentLabel(id) {
  return departmentOptions.value.find(option => String(option.value) === String(id))?.label || String(id || '未分配');
}
const scopeDimensions = { platform_ids: '平台', site_ids: '站点/国家', store_ids: '店铺', warehouse_ids: '仓库', supplier_ids: '供应商' };
function formatScope(scopes) {
  if (!scopes?.length) return '未返回范围';
  return scopes.map(scope => {
    if (typeof scope === 'string') return scope === 'all' ? '租户全部范围' : scope;
    if (scope.scope_type === 'all') return '租户全部范围';
    return Object.entries(scope.config || scope).map(([key, values]) => `${scopeDimensions[key] || key}：${Array.isArray(values) ? values.join('、') : values}`).join('；') || '自定义范围';
  }).join('；');
}
function formatSources(sources) {
  if (!sources?.length) return '无匹配来源';
  return effectivePermissionSourceLabels({sources}, roleOptions.value).join('、') || '无匹配来源';
}
function formatChecklist(items) {
  if (!Array.isArray(items)) return '暂无待办项';
  return items.map(item => `${item.item || '待办事项'}：${({ active: '当前有效', blocked: '已停用', revoke_on_offboard: '离职时收回', download_rechecked_and_blocked: '下载时重新校验并阻止', requires_current_actor_recheck: '需由当前操作者重新校验', manual_owner_review_no_shared_credentials_deleted: '需人工确认凭据归属，不删除共享凭据' })[item.status] || item.status || '待核对'}`).join('；') || '暂无待办项';
}
function refreshAuthorizationView() { resourcePage.value?.loadData(); }
async function openEffectivePermissions(row) {
  effectiveTab.value='permissions';
  if (!roleAccess.value.allowed) return;
  const loadToken = effectiveLoads.begin(); simulationLoads.begin(); simulating.value = false;
  selectedUser.value = row; effectiveDrawerOpen.value = true; effectiveLoading.value = true; effectiveError.value = ''; effectiveData.value = null; organizationData.value = null; simulationResult.value = null;
  const [response, bindings] = await Promise.all([fetchEffectivePermissions(row.id), loadOrganization(row.id)]);
  if (!loadToken.isCurrent() || selectedUser.value.id !== row.id) return;
  effectiveLoading.value = false;
  if (!response?.success) { effectiveError.value = response?.message || '有效权限加载失败'; return; }
  effectiveData.value = response.data;
  if (!bindings) organizationError.value ||= '组织岗位信息加载失败';
}
async function loadOrganization(userId, { preserveDepartment = false } = {}) {
  const sequence = ++organizationLoadSequence;
  organizationLoading.value = true; organizationError.value = '';
  organizationData.value = null;
  const response = await fetchOrganizationBindings(userId);
  if (sequence !== organizationLoadSequence) return false;
  organizationLoading.value = false;
  if (!response?.success) { organizationData.value = null; organizationError.value = response?.message || '组织岗位信息加载失败'; return false; }
  const rolesReady = roleOptions.value.length > 0 || await loadAssignableRoles();
  if (!rolesReady || sequence !== organizationLoadSequence) return false;
  if (!treeNodes.value.length) await loadTree();
  if (sequence !== organizationLoadSequence) return false;
  organizationData.value = response.data;
  const memberships = response.data?.memberships || [];
  const departmentId = preserveDepartment ? organizationForm.department_id : (selectedUser.value.department_id ?? memberships[0]?.department_id ?? null);
  suppressDepartmentReload = true;
  organizationForm.department_id = departmentId;
  suppressDepartmentReload = false;
  const membership = memberships.find(item => String(item.department_id) === String(departmentId) && item.status === 'active')
    || memberships.find(item => String(item.department_id) === String(departmentId)) || null;
  const positionBindings = (response.data?.bindings || []).filter(binding => (
    membership && String(binding.membership_id) === String(membership.id) && binding.source === 'position'
  ));
  organizationForm.role_codes = positionBindings.map(binding => binding.role_code || roleOptions.value.find(role => String(role.id) === String(binding.role_id))?.code).filter(Boolean);
  organizationForm.status = membership?.status === 'inactive' ? 'inactive' : 'active';
  const expires = positionBindings.find(binding => binding.valid_until)?.valid_until || membership?.valid_until;
  organizationForm.valid_until = expires ? String(expires).slice(0,16) : '';
  return true;
}
watch(() => organizationForm.department_id, () => {
  if (!suppressDepartmentReload && effectiveDrawerOpen.value && selectedUser.value.id) loadOrganization(selectedUser.value.id, { preserveDepartment: true });
}, { flush: 'sync' });
async function saveOrganization() {
  if (!roleAccess.value.allowed || !departmentFieldVisible.value || !organizationData.value || !selectedUser.value.id) return;
  organizationSaving.value = true; organizationError.value = '';
  const payload = { expected_version: organizationData.value.authorization_version, department_id: organizationForm.department_id, role_codes: organizationForm.role_codes, status: organizationForm.status };
  if (organizationForm.valid_until) payload.valid_until = new Date(organizationForm.valid_until).toISOString();
  const response = await saveOrganizationBindings(selectedUser.value.id, payload); organizationSaving.value = false;
  if (!response?.success) { organizationError.value = response?.http_status === 409 ? '授权版本冲突，请重新加载组织岗位后再保存。' : response?.message || '组织岗位保存失败'; return; }
  ElMessage.success('组织岗位已保存'); await loadOrganization(selectedUser.value.id);
  const refreshed = await auth.refreshCurrentUser();
  if (!refreshed?.success) organizationError.value = '组织岗位已保存，但当前会话权限刷新失败；敏感操作已暂停。';
}
async function runSimulation() {
  if (!roleAccess.value.allowed || !selectedUser.value.id || !simulateCode.value.trim()) return;
  const loadToken = simulationLoads.begin(), userId = selectedUser.value.id, permissionCode = simulateCode.value.trim();
  simulating.value = true; const response = await simulateAuthorization({ user_id: userId, permission_code: permissionCode });
  if (!loadToken.isCurrent()) return;
  simulating.value = false;
  if (selectedUser.value.id !== userId || simulateCode.value.trim() !== permissionCode) return;
  if (!response?.success) { effectiveError.value = response?.message || '授权模拟失败'; return; }
  simulationResult.value = response.data;
}

const columns = computed(() => [
  auth.hasFieldPermission('field.system.users.full_name.view') ? {prop:'full_name',label:'姓名与账号',type:'identity',width:175,format:(value,row)=>value || row.username} : {prop:'username',label:'账号',width:175},
  ...(departmentFieldVisible.value ? [{prop:'department_name',label:'所属部门',width:155}] : []),
  ...(auth.hasFieldPermission('field.system.users.roles.view') ? [{prop:'role_labels',label:'已分配角色',type:'list',width:190}] : []),
  ...(auth.hasFieldPermission('field.system.users.status.view') ? [{prop:'is_active',label:'状态',type:'status',width:90}] : []),
]);

const detailColumns = computed(()=>[...columns.value,{prop:'email_masked',label:'邮箱（脱敏）'},{prop:'phone_masked',label:'手机（脱敏）'}]);

const formFields = [
  { key: 'full_name', label: '姓名', placeholder: '请输入真实姓名' },
  { key: 'username', label: '用户名', required: true, placeholder: '仅使用工作账号标识', readonly: (_form, editing) => Boolean(editing) },
  { key: 'email', label: '邮箱', placeholder: '请输入工作邮箱（可选）', helpText: (_form, editing) => editing ? '编辑时留空表示不修改。' : '' },
  { key: 'phone', label: '手机号', placeholder: '请输入手机号（可选）', helpText: (_form, editing) => editing ? '编辑时留空表示不修改。' : '' },
  { key: 'initial_password', label: '初始密码', type: 'password', required: true, createOnly: true, placeholder: '至少12位，提交后不回显' },
  {
    key: 'user_type', label: '用户类型', type: 'select', default: 'internal', createOnly: true,
    options: [{ label: '内部用户', value: 'internal' }, { label: '自动化用户', value: 'rpa' }],
  },
  {
    key: 'department_id',
    label: '主部门',
    type: 'select',
    default: null,
    options: () => departmentOptions.value,
    visible: (form) => departmentFieldVisible.value && form.user_type === 'internal',
    clearable: true,
    placeholder: '请选择主部门（可稍后调整）',
    helpText: '主部门用于组织归属和下级数据范围计算。',
    loading: () => treeLoading.value,
  },
  {
    key: 'role_codes',
    label: '角色',
    type: 'select',
    createOnly: true,
    multiple: true,
    default: [],
    options: () => roleOptions.value.map((role) => ({ label: adminRoleDisplayName(role), value: role.code })),
    visible: () => roleAccess.value.allowed,
    placeholder: '可多选角色（可稍后分配）',
    helpText: '仅显示当前账号有权分配的当前租户角色。',
    loading: () => roleOptionsLoading.value,
  },
];

function flattenTree(nodes, result = []) {
  for (const node of nodes || []) {
    result.push({ label: departmentDisplayName(node.name), value: node.id });
    flattenTree(node.children, result);
  }
  return result;
}

const departmentOptions = computed(() => flattenTree(treeNodes.value));

function unpackTree(response) {
  return response?.data?.items || response?.data?.results || [];
}

async function loadTree() {
  if (!departmentTreeVisible.value) {
    treeLoading.value = false;
    treeError.value = '';
    treeNodes.value = [];
    return true;
  }
  treeLoading.value = true;
  treeError.value = '';
  const response = await fetchDepartmentTree();
  treeLoading.value = false;
  if (!response?.success) {
    treeError.value = response?.message || '组织树加载失败';
    treeNodes.value = [];
    return false;
  }
  treeNodes.value = unpackTree(response);
  return true;
}

async function loadAssignableRoles() {
  roleOptionsLoading.value = true;
  const rows = []; let page = 1; let response = null;
  while (page <= 1000) {
    response = await fetchAssignableRoles({ page, page_size: 100 });
    if (!response?.success) break;
    rows.push(...(response.data?.results || response.data?.items || []));
    const count = Number(response.data?.count);
    if (!response.data?.next || (Number.isFinite(count) && rows.length >= count)) break;
    page += 1;
  }
  roleOptionsLoading.value = false;
  if (!response?.success) {
    roleOptions.value = [];
    ElMessage.error(response?.message || '角色目录加载失败');
    return false;
  }
  roleOptions.value = rows;
  return true;
}

async function prepareCreateForm() {
  const treeReady = await loadTree();
  const rolesReady = roleAccess.value.allowed ? await loadAssignableRoles() : true;
  if (!treeReady || !rolesReady) {
    ElMessage.error('新建用户所需的组织或角色选项加载失败，请重试');
    return false;
  }
  return true;
}

function selectDepartment(node) {
  departmentFilters.department_id = node.id;
  departmentFilters.include_descendants = false;
  departmentFilters.unassigned = false;
  reloadUsers();
}

function selectAllUsers() {
  departmentFilters.department_id = undefined;
  departmentFilters.include_descendants = false;
  departmentFilters.unassigned = false;
  reloadUsers();
}

function selectUnassigned() {
  departmentFilters.department_id = undefined;
  departmentFilters.include_descendants = false;
  departmentFilters.unassigned = true;
  reloadUsers();
}

function reloadUsers() {
  resourcePage.value?.loadData();
}

function openDepartmentDialog(row) {
  if (!departmentFieldVisible.value || !departmentAccess.value.allowed) {
    ElMessage.warning(departmentAccess.value.reason || '无权调整部门');
    return;
  }
  selectedUser.value = row;
  selectedDepartmentId.value = row.department_id ?? null;
  selectedDepartmentIds.value = [...(row.department_ids || [])];
  departmentDialogOpen.value = true;
}

async function saveDepartmentAssignment() {
  if (!departmentAccess.value.allowed || !selectedUser.value.id) return;
  departmentSaving.value = true;
  const departmentIds = [...new Set(selectedDepartmentIds.value)];
  if (selectedDepartmentId.value && !departmentIds.includes(selectedDepartmentId.value)) {
    departmentIds.unshift(selectedDepartmentId.value);
  }
  const response = await updateUserDepartments(
    selectedUser.value.id,
    selectedDepartmentId.value,
    departmentIds,
  );
  departmentSaving.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '部门保存失败');
    return;
  }
  ElMessage.success('部门归属已保存并记录审计');
  departmentDialogOpen.value = false;
  await resourcePage.value?.loadData();
  await loadTree();
}

const handleStatus = (row, status) => updateUserStatus(row.id, status === 'active');

function handleUserEdit(id, payload) {
  const next = { ...payload };
  if (!String(next.email || '').trim()) delete next.email;
  if (!String(next.phone || '').trim()) delete next.phone;
  delete next.initial_password;
  delete next.role_codes;
  delete next.user_type;
  return updateUserProfile(id, next);
}

function openPasswordReset(row) {
  if (!roleAccess.value.allowed) {
    ElMessage.warning(roleAccess.value.reason || '无权重置密码');
    return;
  }
  selectedUser.value = row;
  passwordForm.new_password = '';
  passwordForm.confirm_password = '';
  passwordDialogOpen.value = true;
}

async function savePasswordReset() {
  if (!roleAccess.value.allowed || !selectedUser.value.id) return;
  if (passwordForm.new_password.length < 12) {
    ElMessage.warning('新密码至少需要12位。');
    return;
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    ElMessage.warning('两次输入的密码不一致。');
    return;
  }
  passwordSaving.value = true;
  const response = await resetUserPassword(selectedUser.value.id, { ...passwordForm });
  passwordSaving.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '密码重置失败');
    return;
  }
  ElMessage.success('用户密码已重置并记录审计');
  passwordDialogOpen.value = false;
}

async function openRoleAssignment(row) {
  if (!roleAccess.value.allowed) {
    ElMessage.warning(roleAccess.value.reason);
    return;
  }
  selectedUser.value = row;
  selectedRoleCodes.value = [...(row.roles || [])];
  roleOptionsLoading.value = true;
  const response = await fetchAssignableRoles({ page: 1, page_size: 100 });
  roleOptionsLoading.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '角色目录加载失败');
    return;
  }
  roleOptions.value = response.data?.results || [];
  roleDialogOpen.value = true;
}

async function saveRoleAssignment() {
  if (!roleAccess.value.allowed || !selectedUser.value.id) {
    ElMessage.warning(roleAccess.value.reason || '无权分配角色');
    return;
  }
  roleSaving.value = true;
  const response = await updateUserRoles(selectedUser.value.id, selectedRoleCodes.value);
  roleSaving.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '角色保存失败');
    return;
  }
  const refreshResponse = await auth.refreshCurrentUser();
  ElMessage.success('用户角色已保存并记录审计');
  if (!refreshResponse?.success) ElMessage.warning('用户角色已保存，但当前会话权限刷新失败，请重新加载或稍后重试。');
  roleDialogOpen.value = false;
  await resourcePage.value?.loadData();
}

onMounted(loadTree);
watch(departmentTreeVisible, (visible) => {
  if (visible && !treeNodes.value.length) loadTree();
});
</script>

<style scoped>
.directory-scope { display: grid; gap: 8px; padding: 10px 0 2px; border-top: 1px solid #e5eaf0; }
.directory-scope strong { color: #334155; font-size: 12px; }
.directory-scope small { color: #64748b; font-size: 11px; line-height: 1.5; }
.role-user { margin: 0 0 16px; color: #475569; }
.department-form { margin-top: 16px; }
.password-form { margin-top: 16px; }

.more-arrow {margin-left:5px;font-size:12px;}.danger-action {color:#d44646;}.effective-subtitle {margin:0 0 22px;color:#73839a;font-size:14px;}.organization-workspace {display:grid;gap:16px;}.organization-workspace h3 {font-size:16px;}.simulation-workspace {display:flex;align-items:center;flex-wrap:wrap;gap:14px;padding:18px 0;}.simulation-workspace h3,.simulation-workspace p {width:100%;margin:0;}.simulation-workspace p {color:#73839a;font-size:14px;}.simulation-workspace .el-select {width:min(520px,100%);}.simulation-workspace .el-alert {width:100%;}.organization-workspace .org-form {max-width:640px;padding:20px;background:#f8faff;border-radius:7px;}
</style>
<style scoped>:global(.effective-drawer .el-drawer__header){padding:24px 24px 0;margin-bottom:12px}:global(.effective-drawer .el-drawer__body){padding:12px 24px 0}:global(.effective-drawer .el-drawer__title){font-size:22px;font-weight:600;color:#14213b;line-height:1.4}@media(max-width:760px){:global(.effective-drawer .el-drawer__header){padding:18px 16px 0}:global(.effective-drawer .el-drawer__body){padding:8px 16px 0}:global(.effective-drawer .el-drawer__title){font-size:18px}}</style>
