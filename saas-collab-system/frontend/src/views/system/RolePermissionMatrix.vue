<template>
  <AppPage
    eyebrow="ACCESS CONTROL"
    title="角色与权限"
    :subtitle="`目标租户：${targetTenantLabel}。统一维护菜单权限、功能操作权限、字段权限和 data_scope。`"
    boundary-note="前端矩阵仅用于配置与解释；每次 API 请求仍由后端重新校验 tenant、用户类型、角色、permission 和 data_scope。"
    :capability="capability"
  >
    <template #action>
      <el-button
        v-if="manageAccess.visible"
        type="primary"
        :disabled="manageAccess.disabled"
        :title="manageAccess.reason"
        @click="createOpen = true"
      >新建角色</el-button>
    </template>

    <section class="access-layers" aria-label="权限分层链">
      <div v-for="(layer, index) in layers" :key="layer.title" class="access-layer">
        <span>{{ index + 1 }}</span>
        <div><strong>{{ layer.title }}</strong><small>{{ layer.note }}</small></div>
      </div>
    </section>

    <section class="matrix-toolbar">
      <el-input v-model="search" clearable placeholder="搜索角色名称或编码" @keyup.enter="searchRoles" />
      <el-button type="primary" @click="searchRoles">查询</el-button>
      <span>权限目录 {{ permissions.length }} 项</span>
    </section>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <el-table v-else :data="roles" border table-layout="fixed">
      <el-table-column v-if="showRoleField('name')" prop="name" label="角色" min-width="160" />
      <el-table-column v-if="showRoleField('code')" prop="code" label="角色编码" min-width="180" />
      <el-table-column label="权限数" width="100">
        <template #default="{ row }">{{ row.permission_codes?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="数据范围" min-width="170">
        <template #default="{ row }">{{ scopeLabel(row.data_scopes?.[0]?.scope_type) }}</template>
      </el-table-column>
      <el-table-column v-if="showRoleField('status')" prop="status" label="状态" width="100">
        <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="290">
        <template #default="{ row }">
          <el-button link type="primary" @click="openRole(row)">{{ manageAccess.allowed && row.code !== 'administrator' ? '配置权限' : '查看权限' }}</el-button>
          <el-button
            v-if="manageAccess.visible && row.code !== 'administrator'"
            link
            :type="row.status === 'active' ? 'warning' : 'success'"
            :disabled="manageAccess.disabled"
            :title="manageAccess.reason"
            @click="toggleRoleStatus(row)"
          >{{ row.status === 'active' ? '停用' : '启用' }}</el-button>
          <el-button
            v-if="manageAccess.visible && row.code !== 'administrator'"
            link
            type="danger"
            :disabled="manageAccess.disabled"
            :title="manageAccess.reason"
            @click="confirmRoleDelete(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <footer v-if="state === 'ready' || total > 0" class="role-pagination">
      <span>共 {{ total }} 个角色</span>
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
        @current-change="load"
      />
    </footer>

    <el-drawer v-model="drawerOpen" title="角色权限配置" size="min(680px, 96vw)">
      <div class="role-heading">
        <div><strong>{{ selectedRole.name }}</strong><span>{{ selectedRole.code }}</span></div>
        <el-tag effect="plain">目标租户：{{ targetTenantLabel }}</el-tag>
      </div>
      <el-form label-position="top">
        <el-form-item label="数据范围">
          <el-radio-group v-model="roleForm.scope_type" :disabled="!manageAccess.allowed || isBuiltInAdministrator" @change="onScopeTypeChange">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="department">本部门</el-radio-button>
            <el-radio-button value="own">本人</el-radio-button>
            <el-radio-button value="custom">自定义</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="roleForm.scope_type === 'department'" label="部门范围说明">
          <el-alert
            title="本部门范围按实际使用者所属部门生效，不需要手工选择部门。"
            type="info"
            :closable="false"
            show-icon
          />
        </el-form-item>
        <el-form-item v-if="roleForm.scope_type === 'custom'" label="自定义范围配置">
          <div class="scope-config-fields">
            <el-alert
              title="至少选择一个授权维度；所有对象必须属于当前租户。"
              type="warning"
              :closable="false"
              show-icon
            />
            <label>
              <span>部门</span>
              <el-select v-model="roleForm.scope_config.department_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选部门">
                <el-option v-for="item in scopeDepartments" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>用户</span>
              <el-select v-model="roleForm.scope_config.user_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选用户">
                <el-option v-for="item in scopeUsers" :key="item.id" :label="formatUserOption(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>角色</span>
              <el-select v-model="roleForm.scope_config.role_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选角色">
                <el-option v-for="item in scopeRoles" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" />
              </el-select>
            </label>
          </div>
        </el-form-item>
        <el-form-item label="权限配置">
          <el-alert
            title="四类授权相互独立：菜单只负责入口显示，功能操作由后端 action 权限校验，字段权限只控制非敏感列显示，数据范围控制记录边界。"
            type="info"
            :closable="false"
            show-icon
          />
          <section v-for="surface in permissionSurfaces" :key="surface.key" class="permission-surface">
            <div class="permission-surface__heading">
              <strong>{{ surface.label }}</strong>
              <small>{{ surface.note }}</small>
            </div>
            <el-checkbox-group v-model="roleForm[surface.key]" :disabled="!manageAccess.allowed" class="permission-groups">
              <section v-for="group in permissionGroupsFor(surface.type)" :key="`${surface.key}-${group.module}`" class="permission-group">
                <strong>{{ group.module }}</strong>
                <el-checkbox v-for="permission in group.items" :key="permission.code" :value="permission.code">
                  <span>{{ permission.name }}</span>
                  <small class="permission-description">{{ permission.description || '暂无权限说明' }}</small>
                  <small class="permission-code">{{ permission.code }}</small>
                </el-checkbox>
              </section>
            </el-checkbox-group>
          </section>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawerOpen = false">关闭</el-button>
        <el-button v-if="manageAccess.visible" type="primary" :disabled="!manageAccess.allowed" :loading="saving" @click="saveRole">保存配置</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="createOpen" title="新建角色" width="min(480px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="角色名称" required><el-input v-model="newRole.name" /></el-form-item>
        <el-form-item label="角色编码" required><el-input v-model="newRole.code" placeholder="例如 operations_viewer" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitRole">保存</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import {
  createRole, deleteRole, fetchAllPermissions, fetchRoleScopeOptions, fetchRoles,
  updateRolePermissions, updateRoleStatus
} from '../../api/systemAdmin';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { statusFromApiResponse } from '../../utils/uiState';

const auth = useAuthStore();
const route = useRoute();
const roles = ref([]);
const permissions = ref([]);
const state = ref('loading');
const capability = ref(useMock ? 'mock' : 'pending');
const errorMessage = ref('');
const search = ref('');
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const drawerOpen = ref(false);
const createOpen = ref(false);
const saving = ref(false);
const selectedRole = ref({});
const targetTenant = ref(null);
const roleForm = reactive({
  permission_codes: [],
  menu_permission_codes: [],
  action_permission_codes: [],
  field_permission_codes: [],
  scope_type: 'own',
  scope_config: {},
});
const newRole = reactive({ name: '', code: '', status: 'active' });
const scopeDepartments = ref([]);
const scopeUsers = ref([]);
const scopeRoles = ref([]);
const manageAccess = computed(() => getActionAccess(auth, { permission: 'system.roles.manage' }));
const isBuiltInAdministrator = computed(() => selectedRole.value?.code === 'administrator');
const targetTenantId = computed(() => {
  const value = route.query.tenant_id;
  return value === undefined || value === null || value === '' ? '' : String(value);
});
const targetTenantLabel = computed(() => {
  const tenant = targetTenant.value;
  if (tenant?.name || tenant?.code) return `${tenant.name || '未命名'}（${tenant.code || `#${tenant.id}`}）`;
  return targetTenantId.value ? `租户 #${targetTenantId.value}` : `当前租户 #${auth.currentUser?.tenant_id || '—'}`;
});

const layers = [
  { title: 'Tenant', note: '租户隔离' }, { title: '用户类型', note: 'internal / external / RPA' },
  { title: 'Role', note: '岗位职责' }, { title: 'Permission', note: '菜单、操作与字段' },
  { title: 'Data scope', note: '数据可见范围' }, { title: '字段与流程', note: '脱敏、审批、审计' }
];

const permissionSurfaces = [
  { key: 'menu_permission_codes', type: 'menu', label: '菜单权限', note: '只控制系统菜单和路由入口显示，不替代后端操作鉴权。' },
  { key: 'action_permission_codes', type: 'action', label: '功能操作权限', note: '按钮/API 的实际授权；旧 permission_codes 会兼容映射到此类。' },
  { key: 'field_permission_codes', type: 'field', label: '字段权限', note: '控制系统管理域非敏感列显示，敏感字段仍由后端强制脱敏。' },
];
const roleFieldPermissions = {
  name: 'field.system.roles.name.view',
  code: 'field.system.roles.code.view',
  status: 'field.system.roles.status.view',
};

function showRoleField(field) {
  return auth.hasFieldPermission(roleFieldPermissions[field]);
}

function permissionGroupsFor(type) {
  const grouped = new Map();
  for (const permission of permissions.value) {
    if ((permission.permission_type || 'action') !== type) continue;
    if (!grouped.has(permission.module)) grouped.set(permission.module, []);
    grouped.get(permission.module).push(permission);
  }
  return [...grouped.entries()].map(([module, items]) => ({ module, items }));
}

function categorizedRoleCodes(role, type) {
  const property = {
    menu: 'menu_permission_codes',
    action: 'action_permission_codes',
    field: 'field_permission_codes',
  }[type];
  if (Array.isArray(role?.[property])) return [...role[property]];
  const known = new Map(permissions.value.map((permission) => [permission.code, permission.permission_type || 'action']));
  return (role?.permission_codes || []).filter((code) => (known.get(code) || 'action') === type);
}

function unpack(response) {
  return response?.data?.results || response?.data?.items || [];
}
function responseCapability(response) {
  const status = response?.data?.api_status || response?.data?.status;
  if (status === 'fallback') return 'degraded';
  if (status) return status;
  if (response?.success) return useMock ? 'mock' : 'pending';
  return response?.http_status ? 'pending' : 'degraded';
}
function scopeLabel(value) {
  return { all: '全部租户内数据', department: '本部门', own: '本人数据', custom: '自定义范围' }[value] || '未配置';
}
function formatUserOption(item) {
  return `${item.username || ''}${item.full_name ? `（${item.full_name}）` : ''}`;
}

async function load() {
  state.value = 'loading';
  const tenantParams = targetTenantId.value ? { tenant_id: targetTenantId.value } : {};
  const [roleResponse, permissionResult] = await Promise.all([
    fetchRoles({ ...tenantParams, search: search.value.trim(), page: page.value, page_size: pageSize }),
    fetchAllPermissions(),
  ]);
  const permissionResponse = permissionResult.response;
  if (!roleResponse.success || !permissionResponse.success) {
    const failed = !roleResponse.success ? roleResponse : permissionResponse;
    state.value = statusFromApiResponse(failed, navigator.onLine);
    errorMessage.value = failed.message;
    capability.value = responseCapability(failed);
    return;
  }
  roles.value = unpack(roleResponse);
  total.value = Number.isFinite(roleResponse.data?.count) ? roleResponse.data.count : roles.value.length;
  permissions.value = permissionResult.rows;
  targetTenant.value = roleResponse.data?.tenant || targetTenant.value || {
    id: targetTenantId.value || auth.currentUser?.tenant_id,
    name: targetTenantId.value ? '' : '当前租户',
    code: '',
  };
  capability.value = responseCapability(roleResponse);
  state.value = roles.value.length ? 'ready' : 'empty';
}
function searchRoles() {
  page.value = 1;
  load();
}

watch(targetTenantId, () => {
  page.value = 1;
  targetTenant.value = null;
  load();
});
function openRole(role) {
  selectedRole.value = role;
  roleForm.menu_permission_codes = categorizedRoleCodes(role, 'menu');
  roleForm.action_permission_codes = categorizedRoleCodes(role, 'action');
  roleForm.field_permission_codes = categorizedRoleCodes(role, 'field');
  roleForm.permission_codes = [
    ...new Set([
      ...roleForm.menu_permission_codes,
      ...roleForm.action_permission_codes,
      ...roleForm.field_permission_codes,
    ]),
  ];
  roleForm.scope_type = role.data_scopes?.[0]?.scope_type || 'own';
  roleForm.scope_config = { ...(role.data_scopes?.[0]?.config || {}) };
  if (roleForm.scope_type === 'custom') ensureCustomScopeShape();
  drawerOpen.value = true;
  loadScopeOptions();
}

function ensureCustomScopeShape() {
  roleForm.scope_config = {
    ...roleForm.scope_config,
    department_ids: Array.isArray(roleForm.scope_config.department_ids) ? [...roleForm.scope_config.department_ids] : [],
    user_ids: Array.isArray(roleForm.scope_config.user_ids) ? [...roleForm.scope_config.user_ids] : [],
    role_ids: Array.isArray(roleForm.scope_config.role_ids) ? [...roleForm.scope_config.role_ids] : [],
  };
}

function onScopeTypeChange(value) {
  if (value === 'custom') ensureCustomScopeShape();
  else roleForm.scope_config = {};
}

async function loadScopeOptions() {
  const response = await fetchRoleScopeOptions(targetTenantId.value ? { tenant_id: targetTenantId.value } : {});
  if (!response?.success) return;
  scopeDepartments.value = response.data?.departments || [];
  scopeUsers.value = response.data?.users || [];
  scopeRoles.value = response.data?.roles || [];
}
async function saveRole() {
  if (!manageAccess.value.allowed) return;
  if (isBuiltInAdministrator.value) {
    ElMessage.info('管理员角色由权限目录自动同步，不能手工修改。');
    return;
  }
  if (roleForm.scope_type === 'custom') {
    ensureCustomScopeShape();
    const config = roleForm.scope_config;
    if (!config.department_ids.length && !config.user_ids.length && !config.role_ids.length) {
      ElMessage.warning('自定义范围至少选择一个部门、用户或角色');
      return;
    }
  }
  saving.value = true;
  const permissionCodes = [
    ...new Set([
      ...roleForm.menu_permission_codes,
      ...roleForm.action_permission_codes,
      ...roleForm.field_permission_codes,
    ]),
  ];
  const response = await updateRolePermissions(
    selectedRole.value.id,
    { ...roleForm, permission_codes: permissionCodes },
    targetTenantId.value || undefined,
  );
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '保存失败');
  ElMessage.success('角色权限已保存并记录审计');
  drawerOpen.value = false;
  load();
}

async function toggleRoleStatus(row) {
  if (!manageAccess.value.allowed || row.code === 'administrator') return;
  const next = row.status === 'active' ? 'inactive' : 'active';
  try {
    await ElMessageBox.confirm(
      `确认将角色“${row.name || row.code}”设为${next === 'active' ? '启用' : '停用'}？`,
      '角色状态变更确认',
      { type: next === 'inactive' ? 'warning' : 'info' },
    );
    const response = await updateRoleStatus(row.id, next, targetTenantId.value || undefined);
    if (!response?.success) throw new Error(response?.message || '角色状态变更失败');
    ElMessage.success('角色状态已更新并记录审计');
    load();
  } catch (error) {
    if (error === 'cancel' || error === 'close') return;
    ElMessage.error(error?.message || '角色状态变更失败');
  }
}

async function confirmRoleDelete(row) {
  if (!manageAccess.value.allowed || row.code === 'administrator') return;
  try {
    await ElMessageBox.confirm(
      `确认删除角色“${row.name || row.code}”？仅在没有绑定用户时允许删除。`,
      '删除角色确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    );
    const response = await deleteRole(row.id, targetTenantId.value || undefined);
    if (!response?.success) throw new Error(response?.message || '角色删除失败');
    ElMessage.success('角色已删除并记录审计');
    load();
  } catch (error) {
    if (error === 'cancel' || error === 'close') return;
    ElMessage.error(error?.message || '角色删除失败');
  }
}
async function submitRole() {
  if (!manageAccess.value.allowed) {
    ElMessage.warning(manageAccess.value.reason);
    return;
  }
  if (!newRole.name || !newRole.code) return ElMessage.warning('请填写角色名称和编码');
  saving.value = true;
  const response = await createRole({ ...newRole }, targetTenantId.value || undefined);
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '保存失败');
  ElMessage.success('角色已创建');
  createOpen.value = false;
  newRole.name = '';
  newRole.code = '';
  page.value = 1;
  load();
}

load();
</script>

<style scoped>
.access-layers { display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; overflow: hidden; }
.access-layer { display: flex; align-items: center; gap: 10px; min-height: 74px; padding: 12px; border-right: 1px solid #e5eaf0; }
.access-layer:last-child { border-right: 0; }
.access-layer > span { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; color: #fff; background: #315c78; font-size: 12px; }
.access-layer strong, .access-layer small { display: block; }
.access-layer strong { color: #172033; font-size: 13px; }
.access-layer small { margin-top: 4px; color: #64748b; font-size: 11px; }
.matrix-toolbar { display: grid; grid-template-columns: minmax(240px, 380px) auto 1fr; gap: 10px; align-items: center; margin: 16px 0; padding: 12px; border: 1px solid #dbe3ec; background: #fff; }
.matrix-toolbar span { justify-self: end; color: #64748b; font-size: 13px; }
.role-pagination { display: flex; align-items: center; justify-content: space-between; padding-top: 12px; color: #64748b; font-size: 13px; }
.role-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; padding-bottom: 14px; border-bottom: 1px solid #e5eaf0; }
.role-heading strong, .role-heading span { display: block; }
.role-heading span { margin-top: 4px; color: #64748b; font-size: 12px; }
.permission-surface { margin-top: 16px; padding: 12px; border: 1px solid #dbe3ec; border-radius: 6px; background: #fbfdff; }
.permission-surface__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.permission-surface__heading strong { color: #172033; font-size: 14px; }
.permission-surface__heading small { color: #64748b; font-size: 11px; }
.permission-groups { display: grid; gap: 12px; width: 100%; }
.permission-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 12px; padding: 12px; border: 1px solid #e5eaf0; }
.permission-group > strong { grid-column: 1 / -1; margin-bottom: 4px; color: #315c78; text-transform: uppercase; font-size: 12px; }
.permission-group .el-checkbox { height: auto; min-height: 36px; margin-right: 0; }
.permission-group span, .permission-group small { display: block; }
.permission-group small { color: #64748b; font-size: 10px; }
.permission-group .permission-description { margin-top: 3px; color: #475569; font-size: 11px; line-height: 1.45; }
.permission-group .permission-code { margin-top: 2px; color: #94a3b8; font-size: 10px; }
.permission-menu-node { grid-column: 1 / -1; display: flex; align-items: baseline; gap: 8px; min-height: 28px; padding-top: 4px; color: #315c78; font-size: 12px; font-weight: 600; }
.permission-menu-node small { color: #94a3b8; font-size: 10px; font-weight: 400; }
.permission-menu-other { color: #9a6700; }
.permission-leaf { min-width: 0; }
.scope-config-fields { display: grid; gap: 12px; width: 100%; }
.scope-config-fields label { display: grid; gap: 6px; color: #475569; font-size: 12px; }
.scope-config-fields :deep(.el-select) { width: 100%; }
@media (max-width: 980px) { .access-layers { grid-template-columns: repeat(3, 1fr); } .access-layer:nth-child(3) { border-right: 0; } .access-layer:nth-child(-n + 3) { border-bottom: 1px solid #e5eaf0; } }
@media (max-width: 640px) { .access-layers { grid-template-columns: repeat(2, 1fr); } .access-layer:nth-child(3) { border-right: 1px solid #e5eaf0; } .access-layer:nth-child(even) { border-right: 0; } .permission-group { grid-template-columns: 1fr; } .permission-surface__heading { display: grid; gap: 4px; } .matrix-toolbar { grid-template-columns: 1fr auto; } .matrix-toolbar span { display: none; } }
</style>
