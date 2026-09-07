<template>
  <AppPage
    eyebrow="权限管理"
    title="角色与权限"
    :subtitle="`目标租户：${targetTenantLabel}。统一维护菜单、操作、字段和数据范围。`"
    boundary-note="页面只负责配置；每次接口请求仍由服务端校验租户、用户、角色和数据范围。"
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

    <section class="access-layers" aria-label="权限分层">
      <div v-for="(layer, index) in layers" :key="layer.title" class="access-layer">
        <span>{{ index + 1 }}</span>
        <div><strong>{{ layer.title }}</strong><small>{{ layer.note }}</small></div>
      </div>
    </section>

    <section class="matrix-toolbar">
      <el-input v-model="search" clearable placeholder="搜索角色名称" @keyup.enter="searchRoles" />
      <el-button type="primary" @click="searchRoles">查询</el-button>
      <span>权限目录 {{ permissions.length }} 项</span>
    </section>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <el-table v-else :data="roles" border table-layout="fixed">
      <el-table-column v-if="showRoleField('name')" label="角色" min-width="160">
        <template #default="{ row }">{{ adminRoleDisplayName(row) }}</template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_protected ? 'warning' : 'info'" effect="plain">{{ roleTypeLabel(row.role_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="权限数" width="100">
        <template #default="{ row }">{{ row.permission_codes?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="数据范围" min-width="170">
        <template #default="{ row }">{{ scopeLabel(row.data_scopes?.[0]) }}</template>
      </el-table-column>
      <el-table-column v-if="showRoleField('status')" prop="status" label="状态" width="100">
        <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="290">
        <template #default="{ row }">
          <el-button link type="primary" @click="openRole(row)">{{ manageAccess.allowed && row.code !== 'administrator' ? '配置权限' : '查看权限' }}</el-button>
          <el-button
            v-if="manageAccess.visible && !row.is_protected"
            link
            :type="row.status === 'active' ? 'warning' : 'success'"
            :disabled="manageAccess.disabled"
            :title="manageAccess.reason"
            @click="toggleRoleStatus(row)"
          >{{ row.status === 'active' ? '停用' : '启用' }}</el-button>
          <el-button
            v-if="manageAccess.visible && !row.is_protected"
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
        <div><strong>{{ adminRoleDisplayName(selectedRole) }}</strong></div>
        <div class="role-heading__tags">
          <el-tag effect="plain">{{ roleTypeLabel(selectedRole.role_type) }}</el-tag>
          <el-tag v-if="selectedRole.is_protected" type="warning" effect="plain">受保护</el-tag>
          <el-tag effect="plain">目标租户：{{ targetTenantLabel }}</el-tag>
        </div>
      </div>
      <el-form label-position="top">
        <el-form-item label="配置方式">
          <el-radio-group v-model="assignmentMode" :disabled="isBuiltInAdministrator">
            <el-radio-button value="quick">快速分配</el-radio-button>
            <el-radio-button value="advanced">高级配置</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <section v-if="assignmentMode === 'quick'" class="quick-assignment">
          <el-alert
            title="按模块选择权限档位；未触及模块保留原有权限。高风险权限不会随档位自动授予。"
            type="info"
            :closable="false"
            show-icon
          />
          <div class="quick-template-row">
            <span>角色模板</span>
            <el-select v-model="selectedTemplate" clearable placeholder="选择模板后可继续调整" @change="applyRoleTemplate">
              <el-option v-for="template in roleTemplates" :key="template.code" :label="template.name" :value="template.code" />
            </el-select>
          </div>
          <el-alert v-if="templateHint" :title="templateHint" type="warning" :closable="false" show-icon />
          <el-collapse v-model="expandedTree.quick" class="permission-tree">
            <el-collapse-item v-for="menu in permissionTree" :key="menu.key" :name="menu.key">
              <template #title>
                <span class="permission-tree__menu-title">{{ menu.label }}</span>
                <small>{{ menu.children.length }} 个模块</small>
              </template>
              <div class="permission-tree__modules">
                <section v-for="module in menu.children" :key="module.key" class="permission-tree__module">
                  <div class="permission-tree__module-heading">
                    <strong>{{ module.label }}</strong>
                    <small>{{ packageForModule(module.module)?.high_risk_codes?.length || 0 }} 项高风险权限需单独确认</small>
                  </div>
                  <el-select
                    v-model="quickSelections[module.module]"
                    :disabled="!manageAccess.allowed"
                    class="permission-tree__level"
                    @change="markQuickModuleTouched(module.module, $event)"
                  >
                    <el-option v-for="level in packageLevels" :key="level.code" :label="level.name" :value="level.code" />
                  </el-select>
                </section>
              </div>
            </el-collapse-item>
          </el-collapse>
          <div v-if="highRiskPermissions.length" class="quick-high-risk">
            <strong>高风险权限单独确认</strong>
            <small>删除、审批、导出、凭证、授权、回滚和生产动作等不会随模块档位自动授予。</small>
            <el-checkbox-group v-model="quickExtraPermissionCodes" :disabled="!manageAccess.allowed" class="permission-groups">
              <el-checkbox v-for="permission in highRiskPermissions" :key="permission.code" :value="permission.code" @change="markHighRiskTouched(permission.code)">
                {{ adminPermissionLabel(permission) }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <el-alert :title="`保存前摘要：将配置 ${quickSelectedModuleCount} 个模块，预计变更 ${quickPermissionCount} 项权限。`" type="success" :closable="false" />
        </section>
        <el-form-item label="数据范围">
          <el-alert
            title="租户隔离始终生效；角色只能访问当前租户数据，不能选择其他租户。"
            type="info"
            :closable="false"
            show-icon
          />
          <el-radio-group v-model="roleForm.scope_type" :disabled="!manageAccess.allowed || isBuiltInAdministrator" @change="onScopeTypeChange">
            <el-radio-button value="all">租户内全部数据</el-radio-button>
            <el-radio-button value="custom">按业务范围限制</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-alert
          v-if="legacyScopeType"
          title="历史组织范围，需重新配置"
          description="该角色保留了旧的组织范围记录。请选择新的数据范围后再保存，系统不会自动扩大为租户内全部数据。"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-form-item v-if="roleForm.scope_type === 'custom'" label="业务范围配置">
          <div class="scope-config-fields">
            <el-alert
              title="至少选择一个业务维度；所有对象必须属于当前租户。财务价格可见性由字段权限控制，审批和导出由功能权限控制。"
              type="warning"
              :closable="false"
              show-icon
            />
            <label>
              <span>平台</span>
              <el-select v-model="roleForm.scope_config.platform_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选平台">
                <el-option v-for="item in scopePlatforms" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>国家/站点</span>
              <el-select v-model="roleForm.scope_config.site_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选国家或站点">
                <el-option v-for="item in scopeSites" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>店铺</span>
              <el-select v-model="roleForm.scope_config.store_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选店铺">
                <el-option v-for="item in scopeStores" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>仓库</span>
              <el-select v-model="roleForm.scope_config.warehouse_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选仓库">
                <el-option v-for="item in scopeWarehouses" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>供应商</span>
              <el-select v-model="roleForm.scope_config.supplier_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选供应商">
                <el-option v-for="item in scopeSuppliers" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
          </div>
        </el-form-item>
        <el-form-item v-if="assignmentMode === 'advanced'" label="权限配置">
          <el-alert
            title="四类授权相互独立：菜单只负责入口显示，功能操作由服务端校验，字段权限只控制非敏感列显示，数据范围控制记录边界。"
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
              <el-collapse v-model="expandedTree[surface.type]" class="permission-tree permission-tree--advanced">
                <el-collapse-item v-for="menu in permissionTreeForSurface(surface.type)" :key="`${surface.key}-${menu.key}`" :name="menu.key">
                  <template #title>
                    <span class="permission-tree__menu-title">{{ menu.label }}</span>
                    <small>{{ permissionCountForMenu(menu, surface.type) }} 项权限</small>
                  </template>
                  <div class="permission-tree__modules">
                    <section
                      v-for="module in menu.children"
                      :key="`${surface.key}-${module.key}`"
                      class="permission-tree__module permission-tree__module--advanced"
                    >
                      <strong>{{ module.label }}</strong>
                      <div class="permission-tree__items">
                        <el-checkbox
                          v-for="permission in permissionItemsForModule(module.module, surface.type)"
                          :key="permission.code"
                          :value="permission.code"
                        >
                          {{ adminPermissionLabel(permission) }}
                        </el-checkbox>
                      </div>
                    </section>
                  </div>
                </el-collapse-item>
              </el-collapse>
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
        <el-form-item label="系统标识" required><el-input v-model="newRole.code" placeholder="用于唯一识别，建议使用小写字母和数字" /></el-form-item>
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
  createRole, deleteRole, fetchAllPermissions, fetchPermissionPackages, fetchRoleScopeOptions, fetchRoles,
  updateRolePermissions, updateRoleStatus
} from '../../api/systemAdmin';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { adminPermissionLabel, adminRoleDisplayName, tenantDisplayName } from '../../utils/adminDisplayLabels';
import { buildPermissionTree } from '../../utils/permissionTree';
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
const assignmentMode = ref('quick');
const packageCatalog = ref([]);
const expandedTree = reactive({ quick: [], menu: [], action: [], field: [] });
const packageLevels = ref([
  { code: 'none', name: '无权限' },
  { code: 'read', name: '只读' },
  { code: 'operate', name: '可操作' },
  { code: 'admin', name: '模块管理员' },
]);
const selectedTemplate = ref('');
const templateHint = ref('');
const quickSelections = reactive({});
const quickTouchedModules = ref(new Set());
const quickExtraPermissionCodes = ref([]);
// Keep explicit confirmation for newly-added high-risk grants.  Existing
// grants remain editable without repeatedly prompting, while quick-package
// and advanced assignment share the same confirmation boundary.
const originalPermissionCodes = ref([]);
const roleForm = reactive({
  permission_codes: [],
  menu_permission_codes: [],
  action_permission_codes: [],
  field_permission_codes: [],
  scope_type: 'all',
  scope_config: {},
});
const newRole = reactive({ name: '', code: '', status: 'active' });
const scopePlatforms = ref([]);
const scopeSites = ref([]);
const scopeStores = ref([]);
const scopeWarehouses = ref([]);
const scopeSuppliers = ref([]);
const legacyScopeType = ref('');
const manageAccess = computed(() => getActionAccess(auth, { permission: 'system.roles.manage' }));
const isBuiltInAdministrator = computed(() => selectedRole.value?.code === 'administrator');
const targetTenantId = computed(() => {
  const value = route.query.tenant_id;
  return value === undefined || value === null || value === '' ? '' : String(value);
});
const targetTenantLabel = computed(() => {
  return tenantDisplayName(targetTenant.value, targetTenantId.value ? '目标租户' : '当前租户');
});
const roleTemplates = [
  { code: 'readonly', name: '只读人员', level: 'read', scope_type: 'all' },
  { code: 'operator', name: '业务操作员', level: 'operate', scope_type: 'all' },
  { code: 'business_scope_manager', name: '业务范围负责人', level: 'operate', scope_type: 'custom' },
  { code: 'security_auditor', name: '安全审计员', level: 'read', scope_type: 'all', modules: ['audit', 'security', 'system'] },
];
const BUSINESS_SCOPE_KEYS = ['platform_ids', 'site_ids', 'store_ids', 'warehouse_ids', 'supplier_ids'];
const LEGACY_SCOPE_TYPES = ['department', 'department_tree', 'own'];
const LEGACY_SCOPE_CONFIG_KEYS = ['department_ids', 'user_ids', 'role_ids'];

const layers = [
  { title: '租户', note: '租户隔离' }, { title: '用户类型', note: '内部、外部、自动化' },
  { title: '角色', note: '岗位职责' }, { title: '权限', note: '菜单、操作与字段' },
  { title: '数据范围', note: '数据可见边界' }, { title: '字段与流程', note: '脱敏、审批、审计' }
];

const permissionSurfaces = [
  { key: 'menu_permission_codes', type: 'menu', label: '菜单权限', note: '只控制系统菜单和路由入口显示，不替代后端操作鉴权。' },
  { key: 'action_permission_codes', type: 'action', label: '功能操作权限', note: '控制按钮和接口的实际授权；历史权限会自动归入此类。' },
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

const permissionTree = computed(() => buildPermissionTree({
  modules: packageCatalog.value.map((item) => item.module),
  permissions: permissions.value,
}));
const packageByModule = computed(() => new Map(packageCatalog.value.map((item) => [item.module, item])));

function packageForModule(module) {
  return packageByModule.value.get(module);
}

function permissionItemsForModule(module, type) {
  return permissions.value.filter((permission) => (
    permission.module === module && (permission.permission_type || 'action') === type
  ));
}

function permissionCountForMenu(menu, type) {
  return menu.children.reduce((count, module) => count + permissionItemsForModule(module.module, type).length, 0);
}

function permissionTreeForSurface(type) {
  return permissionTree.value
    .map((menu) => ({
      ...menu,
      children: menu.children.filter((module) => permissionItemsForModule(module.module, type).length),
    }))
    .filter((menu) => menu.children.length);
}

watch(permissionTree, (tree) => {
  if (!tree.length) return;
  if (!expandedTree.quick.length) expandedTree.quick = [tree[0].key];
  for (const type of ['menu', 'action', 'field']) {
    const surfaceTree = permissionTreeForSurface(type);
    if (!expandedTree[type].length && surfaceTree.length) expandedTree[type] = [surfaceTree[0].key];
  }
}, { immediate: true });

const highRiskPermissions = computed(() => {
  const codes = new Set(packageCatalog.value.flatMap((item) => item.high_risk_codes || []));
  return permissions.value.filter((permission) => codes.has(permission.code));
});
const quickSelectedModuleCount = computed(() => Object.values(quickSelections).filter((value) => value && value !== 'none').length);
const quickPermissionCount = computed(() => {
  let count = 0;
  for (const item of packageCatalog.value) {
    const level = quickSelections[item.module] || 'none';
    count += (item.levels?.[level] || []).length;
  }
  count += quickExtraPermissionCodes.value.filter((code) => quickTouchedModules.value.has(permissionModuleForCode(code))).length;
  return count;
});

const candidatePermissionCodes = computed(() => {
  if (assignmentMode.value !== 'quick') {
    return [...new Set([
      ...roleForm.menu_permission_codes,
      ...roleForm.action_permission_codes,
      ...roleForm.field_permission_codes,
    ])];
  }
  const touchedModules = quickTouchedModules.value;
  const touchedCodes = packageCatalog.value.flatMap((item) => (
    touchedModules.has(item.module) ? (item.levels?.[quickSelections[item.module] || 'none'] || []) : []
  ));
  const untouchedCodes = roleForm.permission_codes.filter(
    (code) => !touchedModules.has(permissionModuleForCode(code)),
  );
  const extraCodes = quickExtraPermissionCodes.value.filter(
    (code) => touchedModules.has(permissionModuleForCode(code)),
  );
  return [...new Set([...touchedCodes, ...extraCodes, ...untouchedCodes])];
});

const pendingHighRiskPermissionCodes = computed(() => {
  const original = new Set(originalPermissionCodes.value);
  const highRiskCodes = new Set(highRiskPermissions.value.map((permission) => permission.code));
  return candidatePermissionCodes.value.filter((code) => highRiskCodes.has(code) && !original.has(code));
});

const pendingHighRiskSummary = computed(() => pendingHighRiskPermissionCodes.value
  .map((code) => highRiskPermissions.value.find((permission) => permission.code === code)?.name || code)
  .filter(Boolean)
  .join('、'));

function permissionModuleForCode(code) {
  return packageCatalog.value.find((item) => (item.available_codes || []).includes(code))?.module || '';
}

function inferQuickSelection(role) {
  quickTouchedModules.value = new Set();
  const highRisk = new Set(packageCatalog.value.flatMap((item) => item.high_risk_codes || []));
  for (const item of packageCatalog.value) {
    const roleCodes = new Set((role?.permission_codes || []).filter((code) => {
      const permission = permissions.value.find((candidate) => candidate.code === code);
      return permission?.module === item.module && !highRisk.has(code);
    }));
    const level = Object.entries(item.levels || {}).find(([, codes]) => {
      const normalized = new Set(codes);
      return normalized.size === roleCodes.size && [...normalized].every((code) => roleCodes.has(code));
    });
    quickSelections[item.module] = level ? level[0] : (roleCodes.size ? 'admin' : 'none');
  }
  quickExtraPermissionCodes.value = (role?.permission_codes || []).filter((code) => highRisk.has(code));
}

function applyRoleTemplate(templateCode) {
  const template = roleTemplates.find((item) => item.code === templateCode);
  if (!template) return;
  templateHint.value = '';
  const selectedModules = packageCatalog.value
    .filter((item) => quickSelections[item.module] && quickSelections[item.module] !== 'none')
    .map((item) => item.module);
  const explicitModules = template.modules || [];
  if (explicitModules.length) {
    quickTouchedModules.value = new Set(explicitModules);
    for (const item of packageCatalog.value) {
      if (explicitModules.includes(item.module)) quickSelections[item.module] = template.level;
    }
  } else if (selectedModules.length) {
    quickTouchedModules.value = new Set([...quickTouchedModules.value, ...selectedModules]);
    for (const module of selectedModules) quickSelections[module] = template.level;
  } else {
    templateHint.value = `“${template.name}”仅提供 ${template.level === 'read' ? '只读' : '可操作'} 档位和数据范围建议；当前角色尚未选择模块，请在下方逐项选择模块。`;
  }
  roleForm.scope_type = template.scope_type;
  legacyScopeType.value = '';
  roleForm.scope_config = {};
  if (roleForm.scope_type === 'custom') ensureCustomScopeShape();
}

function markQuickModuleTouched(module, level) {
  quickTouchedModules.value = new Set([...quickTouchedModules.value, module]);
  if (level === 'none') {
    quickExtraPermissionCodes.value = quickExtraPermissionCodes.value.filter(
      (code) => permissionModuleForCode(code) !== module,
    );
  }
}

function markHighRiskTouched(code) {
  const module = packageCatalog.value.find((item) => (item.high_risk_codes || []).includes(code))?.module;
  if (module) markQuickModuleTouched(module);
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
function scopeLabel(scope) {
  const value = typeof scope === 'string' ? scope : scope?.scope_type;
  const config = typeof scope === 'object' ? scope?.config || {} : {};
  if (LEGACY_SCOPE_TYPES.includes(value) || (
    value === 'custom' && LEGACY_SCOPE_CONFIG_KEYS.some((key) => Object.prototype.hasOwnProperty.call(config, key))
  )) {
    return '历史组织范围，需重新配置';
  }
  return {
    all: '租户内全部数据',
    custom: '按业务范围限制',
  }[value] || '未配置';
}
function roleTypeLabel(value) {
  return { builtin: '内置角色', template: '角色模板', custom: '自定义角色' }[value] || '自定义角色';
}
function scopeOptionLabel(item) {
  const name = item?.name || item?.code || `对象${item?.id || ''}`;
  const suffix = item?.country_code ? `（${item.country_code}）` : '';
  return `${name}${suffix}`;
}

async function load() {
  state.value = 'loading';
  const tenantParams = targetTenantId.value ? { tenant_id: targetTenantId.value } : {};
  const [roleResponse, permissionResult, packageResponse] = await Promise.all([
    fetchRoles({ ...tenantParams, search: search.value.trim(), page: page.value, page_size: pageSize }),
    fetchAllPermissions(),
    fetchPermissionPackages(tenantParams),
  ]);
  const permissionResponse = permissionResult.response;
  if (!roleResponse.success || !permissionResponse.success || !packageResponse.success) {
    const failed = !roleResponse.success ? roleResponse : (!permissionResponse.success ? permissionResponse : packageResponse);
    state.value = statusFromApiResponse(failed, navigator.onLine);
    errorMessage.value = failed.message;
    capability.value = responseCapability(failed);
    return;
  }
  roles.value = unpack(roleResponse);
  total.value = Number.isFinite(roleResponse.data?.count) ? roleResponse.data.count : roles.value.length;
  permissions.value = permissionResult.rows;
  packageCatalog.value = packageResponse.data?.packages || [];
  packageLevels.value = packageResponse.data?.levels || packageLevels.value;
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
  originalPermissionCodes.value = [...new Set(role.permission_codes || [])];
  assignmentMode.value = 'quick';
  selectedTemplate.value = '';
  inferQuickSelection(role);
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
  const savedScope = role.data_scopes?.[0] || {};
  const savedType = savedScope.scope_type || 'all';
  const savedConfig = { ...(savedScope.config || {}) };
  const hasLegacyConfig = LEGACY_SCOPE_CONFIG_KEYS.some((key) => Object.prototype.hasOwnProperty.call(savedConfig, key));
  const isLegacy = LEGACY_SCOPE_TYPES.includes(savedType) || (savedType === 'custom' && hasLegacyConfig);
  legacyScopeType.value = isLegacy ? savedType : '';
  roleForm.scope_type = isLegacy ? '' : (savedType === 'custom' ? 'custom' : 'all');
  roleForm.scope_config = isLegacy ? {} : savedConfig;
  if (roleForm.scope_type === 'custom') ensureCustomScopeShape();
  drawerOpen.value = true;
  loadScopeOptions();
}

function ensureCustomScopeShape() {
  const current = roleForm.scope_config || {};
  roleForm.scope_config = Object.fromEntries(
    BUSINESS_SCOPE_KEYS.map((key) => [key, Array.isArray(current[key]) ? [...current[key]] : []]),
  );
}

function onScopeTypeChange(value) {
  legacyScopeType.value = '';
  if (value === 'custom') ensureCustomScopeShape();
  else roleForm.scope_config = {};
}

async function loadScopeOptions() {
  const response = await fetchRoleScopeOptions(targetTenantId.value ? { tenant_id: targetTenantId.value } : {});
  if (!response?.success) return;
  scopePlatforms.value = response.data?.platforms || [];
  scopeSites.value = response.data?.sites || [];
  scopeStores.value = response.data?.stores || [];
  scopeWarehouses.value = response.data?.warehouses || [];
  scopeSuppliers.value = response.data?.suppliers || [];
}
async function saveRole() {
  if (!manageAccess.value.allowed) return;
  if (isBuiltInAdministrator.value) {
    ElMessage.info('管理员角色由权限目录自动同步，不能手工修改。');
    return;
  }
  if (legacyScopeType.value) {
    ElMessage.warning('该角色使用历史组织范围，请先明确选择新的数据范围。');
    return;
  }
  if (!['all', 'custom'].includes(roleForm.scope_type)) {
    ElMessage.warning('请选择租户内全部数据或按业务范围限制。');
    return;
  }
  let scopeConfig = {};
  if (roleForm.scope_type === 'custom') {
    ensureCustomScopeShape();
    scopeConfig = Object.fromEntries(
      BUSINESS_SCOPE_KEYS
        .filter((key) => roleForm.scope_config[key].length)
        .map((key) => [key, [...roleForm.scope_config[key]]]),
    );
    if (!Object.keys(scopeConfig).length) {
      ElMessage.warning('业务范围至少选择一个平台、国家/站点、店铺、仓库或供应商。');
      return;
    }
  }
  if (pendingHighRiskPermissionCodes.value.length) {
    try {
      await ElMessageBox.confirm(
        `当前将新增 ${pendingHighRiskPermissionCodes.value.length} 项高风险权限：${pendingHighRiskSummary.value}。该授权会写入角色并记录审计，确认继续吗？`,
        '确认授予高风险权限',
        { type: 'warning', confirmButtonText: '确认授予', cancelButtonText: '取消' },
      );
    } catch (error) {
      if (error === 'cancel' || error === 'close') return;
      ElMessage.error(error?.message || '高风险权限确认失败');
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
  const payload = assignmentMode.value === 'quick'
    ? {
        package_selections: Object.fromEntries(
          [...quickTouchedModules.value].map((module) => [module, quickSelections[module] || 'none']),
        ),
        extra_permission_codes: quickExtraPermissionCodes.value.filter(
          (code) => quickTouchedModules.value.has(permissionModuleForCode(code)),
        ),
        scope_type: roleForm.scope_type,
        scope_config: scopeConfig,
      }
    : { ...roleForm, permission_codes: permissionCodes, scope_config: scopeConfig };
  const response = await updateRolePermissions(
    selectedRole.value.id,
    payload,
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
  if (!newRole.name || !newRole.code) return ElMessage.warning('请填写角色名称和系统标识');
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
.role-heading__tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.quick-assignment { display: grid; gap: 12px; margin-bottom: 18px; }
.quick-template-row { display: grid; grid-template-columns: 90px minmax(180px, 1fr); gap: 10px; align-items: center; color: #475569; font-size: 12px; }
.quick-high-risk { display: grid; gap: 6px; padding: 12px; border: 1px solid #f1d29a; border-radius: 6px; background: #fffaf0; }
.quick-high-risk small { color: #7c5b16; font-size: 11px; line-height: 1.5; }
.permission-tree { width: 100%; min-width: 0; border: 1px solid #dbe3ec; border-radius: 6px; background: #fff; overflow: hidden; }
.permission-tree :deep(.el-collapse-item__header) { min-width: 0; padding: 0 12px; color: #172033; font-size: 13px; }
.permission-tree :deep(.el-collapse-item__wrap) { min-width: 0; }
.permission-tree :deep(.el-collapse-item__content) { min-width: 0; padding: 0 12px 12px; }
.permission-tree__menu-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.permission-tree__menu-title + small { margin-left: auto; padding-left: 12px; color: #64748b; font-size: 11px; white-space: nowrap; }
.permission-tree__modules { display: grid; gap: 8px; min-width: 0; }
.permission-tree__module { display: grid; grid-template-columns: minmax(0, 1fr) minmax(150px, 220px); gap: 12px; align-items: center; min-width: 0; padding: 10px; border: 1px solid #e5eaf0; border-radius: 6px; background: #fbfdff; }
.permission-tree__module-heading { display: grid; gap: 3px; min-width: 0; }
.permission-tree__module-heading strong, .permission-tree__module-heading small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.permission-tree__module-heading strong, .permission-tree__module--advanced > strong { color: #315c78; font-size: 13px; }
.permission-tree__module-heading small { color: #64748b; font-size: 11px; }
.permission-tree__level { width: 100%; min-width: 0; }
.permission-tree__module--advanced { grid-template-columns: minmax(110px, 170px) minmax(0, 1fr); align-items: start; }
.permission-tree__items { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 12px; min-width: 0; }
.permission-tree__items .el-checkbox { min-width: 0; height: auto; margin: 0; }
.permission-tree__items :deep(.el-checkbox__label) { min-width: 0; overflow-wrap: anywhere; white-space: normal; }
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
.permission-menu-node { grid-column: 1 / -1; display: flex; align-items: baseline; gap: 8px; min-height: 28px; padding-top: 4px; color: #315c78; font-size: 12px; font-weight: 600; }
.permission-menu-node small { color: #94a3b8; font-size: 10px; font-weight: 400; }
.permission-menu-other { color: #9a6700; }
.permission-leaf { min-width: 0; }
.scope-config-fields { display: grid; gap: 12px; width: 100%; }
.scope-config-fields label { display: grid; gap: 6px; color: #475569; font-size: 12px; }
.scope-config-fields :deep(.el-select) { width: 100%; }
@media (max-width: 980px) { .access-layers { grid-template-columns: repeat(3, 1fr); } .access-layer:nth-child(3) { border-right: 0; } .access-layer:nth-child(-n + 3) { border-bottom: 1px solid #e5eaf0; } }
@media (max-width: 640px) { .access-layers { grid-template-columns: repeat(2, 1fr); } .access-layer:nth-child(3) { border-right: 1px solid #e5eaf0; } .access-layer:nth-child(even) { border-right: 0; } .permission-tree__module, .permission-tree__module--advanced { grid-template-columns: 1fr; } .permission-tree__items { grid-template-columns: 1fr; } .permission-surface__heading { display: grid; gap: 4px; } .matrix-toolbar { grid-template-columns: 1fr auto; } .matrix-toolbar span { display: none; } }
</style>
