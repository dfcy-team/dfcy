<template>
  <AppPage
    eyebrow="ACCESS CONTROL"
    title="角色与六层权限"
    subtitle="以当前租户为边界，统一维护角色、权限码和 data_scope。"
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

    <section class="access-layers" aria-label="六层权限链">
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
      <el-table-column prop="name" label="角色" min-width="160" />
      <el-table-column prop="code" label="角色编码" min-width="180" />
      <el-table-column label="权限数" width="100">
        <template #default="{ row }">{{ row.permission_codes?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="数据范围" min-width="170">
        <template #default="{ row }">{{ scopeLabel(row.data_scopes?.[0]?.scope_type) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="130">
        <template #default="{ row }">
          <el-button link type="primary" @click="openRole(row)">{{ manageAccess.allowed && row.code !== 'administrator' ? '配置权限' : '查看权限' }}</el-button>
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
        <el-tag effect="plain">tenant {{ selectedRole.tenant_id }}</el-tag>
      </div>
      <el-alert
        v-if="isBuiltInAdministrator"
        class="administrator-note"
        type="info"
        :closable="false"
        show-icon
        title="管理员角色由权限目录自动同步，不能手工修改权限或数据范围。"
      />
      <el-form label-position="top">
        <el-form-item label="数据范围">
          <el-radio-group v-model="roleForm.scope_type" :disabled="!manageAccess.allowed || isBuiltInAdministrator">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="department">本部门</el-radio-button>
            <el-radio-button value="own">本人</el-radio-button>
            <el-radio-button value="custom">自定义</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="权限码">
          <el-checkbox-group v-model="roleForm.permission_codes" :disabled="!manageAccess.allowed || isBuiltInAdministrator" class="permission-groups">
            <section v-for="group in permissionGroups" :key="group.module" class="permission-group">
              <strong>{{ group.label }}</strong>
              <template v-for="permission in group.items" :key="permission.key">
                <div
                  v-if="permission.type === 'menu'"
                  class="permission-menu-node"
                  :class="{ 'permission-menu-other': permission.other }"
                  :style="{ paddingLeft: `${12 + permission.depth * 18}px` }"
                >
                  <span>{{ permission.label }}</span>
                  <small v-if="permission.path">{{ permission.path }}</small>
                </div>
                <el-checkbox
                  v-else
                  class="permission-leaf"
                  :style="{ marginLeft: `${permission.depth * 18}px` }"
                  :value="permission.code"
                  :disabled="permission.unavailable"
                >
                  <span>{{ permissionLabel(permission) }}</span><small>{{ permission.code }}<template v-if="permission.unavailable">（目录未返回）</template></small>
                </el-checkbox>
              </template>
            </section>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawerOpen = false">关闭</el-button>
        <el-button v-if="manageAccess.visible && !isBuiltInAdministrator" type="primary" :disabled="!manageAccess.allowed" :loading="saving" @click="saveRole">保存配置</el-button>
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
import { computed, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { createRole, fetchPermissions, fetchRoles, updateRolePermissions } from '../../api/systemAdmin';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { statusFromApiResponse } from '../../utils/uiState';
import { permissionLabel } from '../../utils/permissionLabels';
import { menuItems, routeCapabilities } from '../../router/menu';

const auth = useAuthStore();
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
const roleForm = reactive({ permission_codes: [], scope_type: 'own', scope_config: {} });
const newRole = reactive({ name: '', code: '', status: 'active' });
const manageAccess = computed(() => getActionAccess(auth, { permission: 'system.roles.manage' }));
const isBuiltInAdministrator = computed(() => selectedRole.value.code === 'administrator');

const layers = [
  { title: 'Tenant', note: '租户隔离' }, { title: '用户类型', note: 'internal / external / RPA' },
  { title: '角色', note: '岗位职责' }, { title: 'Permission', note: '页面与动作' },
  { title: 'Data scope', note: '数据可见范围' }, { title: '字段与流程', note: '脱敏、审批、审计' }
];

const permissionGroups = computed(() => {
  const byCode = new Map(
    permissions.value
      .filter((permission) => permission?.code)
      .map((permission) => [permission.code, permission]),
  );
  const seenCodes = new Set();
  const mappedCodes = new Set();
  const groups = [];
  const routePermissions = (path) => routeCapabilities
    .filter((capability) => capability.path === path)
    .flatMap((capability) => capability.permissions || []);
  const codesFor = (item) => [...new Set([...(item.permissions || []), ...routePermissions(item.path)])];
  const descendantCodes = (item) => new Set((item.children || []).flatMap((child) => [
    ...codesFor(child), ...[...descendantCodes(child)],
  ]));

  function appendMenuNode(items, item, depth, key) {
    const children = item.children || [];
    const descendantCodeSet = descendantCodes(item);
    const ownCodes = codesFor(item).filter((code) => !descendantCodeSet.has(code));
    items.push({
      type: 'menu',
      key: `menu:${key}`,
      label: item.label || item.path || '未命名菜单',
      path: item.path || '',
      depth,
    });
    for (const code of ownCodes) {
      mappedCodes.add(code);
      if (seenCodes.has(code)) continue;
      seenCodes.add(code);
      items.push({
        ...(byCode.get(code) || { code, name: code, module: '', action: '', unavailable: true }),
        type: 'permission',
        key: `permission:${code}`,
        code,
        depth: depth + 1,
        unavailable: !byCode.has(code),
      });
    }
    children.forEach((child, index) => appendMenuNode(items, child, depth + 1, `${key}.${index}`));
  }

  menuItems.forEach((root, index) => {
    const items = [];
    appendMenuNode(items, root, 0, String(index));
    groups.push({ module: `menu:${index}`, label: root.label || `菜单 ${index + 1}`, items });
  });

  // Keep every catalog permission configurable, including management/action
  // codes that do not have a visible menu route.  Route capabilities that are
  // not represented in menu.js are also retained here (as disabled entries if
  // the backend catalog has not caught up yet).
  const routeOnlyCodes = new Set(routeCapabilities.flatMap((item) => item.permissions || []));
  const otherItems = [];
  for (const permission of permissions.value) {
    if (permission?.code && !mappedCodes.has(permission.code)) {
      otherItems.push({ ...permission, type: 'permission', key: `permission:${permission.code}`, depth: 1 });
      mappedCodes.add(permission.code);
    }
  }
  for (const code of routeOnlyCodes) {
    if (seenCodes.has(code) || mappedCodes.has(code)) continue;
    otherItems.push({
      ...(byCode.get(code) || { code, name: code, module: '', action: '', unavailable: true }),
      type: 'permission',
      key: `permission:${code}`,
      code,
      depth: 1,
      unavailable: !byCode.has(code),
    });
    mappedCodes.add(code);
  }
  if (otherItems.length) {
    groups.push({ module: 'other', label: '其他操作权限', items: [
      { type: 'menu', key: 'menu:other', label: '其他操作权限', path: '', depth: 0, other: true },
      ...otherItems,
    ] });
  }
  return groups;
});

function unpack(response) {
  return response?.data?.results || response?.data?.items || [];
}
async function loadAllPermissions() {
  const pageSize = 100;
  const collected = [];
  let pageNumber = 1;
  let totalCount = null;
  let firstResponse = null;
  while (pageNumber <= 1000) {
    const response = await fetchPermissions({ page: pageNumber, page_size: pageSize });
    if (!firstResponse) firstResponse = response;
    if (!response.success) return response;
    const batch = unpack(response);
    collected.push(...batch);
    const responseTotal = Number(response.data?.count);
    if (Number.isFinite(responseTotal)) totalCount = responseTotal;
    const next = response.data?.next;
    if (!batch.length) break;
    if (!next && ((totalCount !== null && collected.length >= totalCount) || batch.length < pageSize)) break;
    pageNumber += 1;
  }
  return {
    ...firstResponse,
    data: {
      ...(firstResponse?.data || {}),
      count: totalCount ?? collected.length,
      results: collected,
      next: null,
      previous: null,
    },
  };
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
async function load() {
  state.value = 'loading';
  const [roleResponse, permissionResponse] = await Promise.all([
    fetchRoles({ search: search.value.trim(), page: page.value, page_size: pageSize }),
    loadAllPermissions(),
  ]);
  if (!roleResponse.success || !permissionResponse.success) {
    const failed = !roleResponse.success ? roleResponse : permissionResponse;
    state.value = statusFromApiResponse(failed, navigator.onLine);
    errorMessage.value = failed.message;
    capability.value = responseCapability(failed);
    return;
  }
  roles.value = unpack(roleResponse);
  total.value = Number.isFinite(roleResponse.data?.count) ? roleResponse.data.count : roles.value.length;
  permissions.value = unpack(permissionResponse);
  capability.value = responseCapability(roleResponse);
  state.value = roles.value.length ? 'ready' : 'empty';
}
function searchRoles() {
  page.value = 1;
  load();
}
function openRole(role) {
  selectedRole.value = role;
  roleForm.permission_codes = [...new Set((role.permission_codes || []).filter(Boolean))];
  roleForm.scope_type = role.data_scopes?.[0]?.scope_type || 'own';
  roleForm.scope_config = role.data_scopes?.[0]?.config || {};
  drawerOpen.value = true;
}
async function saveRole() {
  if (!manageAccess.value.allowed) return;
  if (isBuiltInAdministrator.value) {
    ElMessage.info('管理员角色由权限目录自动同步，不能手工修改。');
    return;
  }
  saving.value = true;
  const realPermissionCodes = new Set(
    permissions.value.map((permission) => permission?.code).filter(Boolean),
  );
  const payload = {
    ...roleForm,
    permission_codes: [...new Set(roleForm.permission_codes)].filter((code) => realPermissionCodes.has(code)),
  };
  const response = await updateRolePermissions(selectedRole.value.id, payload);
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '保存失败');
  ElMessage.success('角色权限已保存并记录审计');
  drawerOpen.value = false;
  load();
}
async function submitRole() {
  if (!manageAccess.value.allowed) {
    ElMessage.warning(manageAccess.value.reason);
    return;
  }
  if (!newRole.name || !newRole.code) return ElMessage.warning('请填写角色名称和编码');
  saving.value = true;
  const response = await createRole({ ...newRole });
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
.permission-groups { display: grid; gap: 12px; width: 100%; }
.permission-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 12px; padding: 12px; border: 1px solid #e5eaf0; }
.permission-group > strong { grid-column: 1 / -1; margin-bottom: 4px; color: #315c78; text-transform: uppercase; font-size: 12px; }
.permission-group .el-checkbox { height: auto; min-height: 36px; margin-right: 0; }
.permission-group span, .permission-group small { display: block; }
.permission-group small { color: #64748b; font-size: 10px; }
.permission-menu-node { grid-column: 1 / -1; display: flex; align-items: baseline; gap: 8px; min-height: 28px; padding-top: 4px; color: #315c78; font-size: 12px; font-weight: 600; }
.permission-menu-node small { color: #94a3b8; font-size: 10px; font-weight: 400; }
.permission-menu-other { color: #9a6700; }
.permission-leaf { min-width: 0; }
@media (max-width: 980px) { .access-layers { grid-template-columns: repeat(3, 1fr); } .access-layer:nth-child(3) { border-right: 0; } .access-layer:nth-child(-n + 3) { border-bottom: 1px solid #e5eaf0; } }
@media (max-width: 640px) { .access-layers { grid-template-columns: repeat(2, 1fr); } .access-layer:nth-child(3) { border-right: 1px solid #e5eaf0; } .access-layer:nth-child(even) { border-right: 0; } .permission-group { grid-template-columns: 1fr; } .matrix-toolbar { grid-template-columns: 1fr auto; } .matrix-toolbar span { display: none; } }
</style>
