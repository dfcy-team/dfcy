<template>
  <AppPage
    eyebrow="权限管理"
    title="角色与权限"
    :subtitle="`目标租户：${targetTenantLabel}。统一维护菜单、操作、字段和数据范围。`"
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

    <details class="permission-guide"><summary>了解权限配置</summary><section class="access-layers" aria-label="权限分层">
      <div v-for="(layer, index) in layers" :key="layer.title" class="access-layer">
        <span>{{ index + 1 }}</span>
        <div><strong>{{ layer.title }}</strong><small>{{ layer.note }}</small></div>
      </div>
    </section>

    </details>
    <section class="matrix-toolbar">
      <el-input v-model="search" clearable placeholder="搜索角色名称或系统标识" @keyup.enter="searchRoles" />
      <el-button type="primary" @click="searchRoles">查询</el-button>
      <span>权限目录 {{ permissions.length }} 项</span>
    </section>

    <el-alert v-if="registryDrift.length" class="permission-drift" type="warning" :closable="false" show-icon
      title="权限目录与注册菜单存在差异"
      :description="`以下菜单尚未登记到 API 目录，不能提交其权限：${registryDrift.map((item) => `${item.name}（${item.code}）`).join('、')}`" />
    <el-alert v-if="permissionCatalogError" class="permission-drift" type="warning" :closable="false" show-icon
      title="角色列表已加载，权限目录暂不可用"
      :description="permissionCatalogError" />
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <el-table v-else :data="roles" border table-layout="fixed">
      <el-table-column v-if="showRoleField('name')" label="角色名称" min-width="140">
        <template #default="{ row }">{{ row.name || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="showRoleField('code')" prop="code" label="系统标识" min-width="150">
        <template #default="{ row }"><span class="role-system-code">{{ row.code || '—' }}</span></template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag :type="row.is_protected ? 'warning' : 'info'" effect="plain">{{ roleTypeLabel(row.role_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="权限数" width="80">
        <template #default="{ row }">{{ row.permission_codes?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="数据范围" min-width="150">
        <template #default="{ row }">{{ scopeLabel(row.data_scopes?.[0]) }}</template>
      </el-table-column>
      <el-table-column v-if="showRoleField('status')" prop="status" label="状态" width="90">
        <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="280">
        <template #default="{ row }">
          <el-button link type="primary" @click="openRole(row)">{{ manageAccess.allowed && row.code !== 'administrator' ? '配置权限' : '查看权限' }}</el-button>
          <el-button v-if="manageAccess.visible" link type="primary" :disabled="manageAccess.disabled" @click="openResourcePolicies(row)">资源范围</el-button>
          <el-button
            v-if="manageAccess.visible"
            link
            type="primary"
            :disabled="manageAccess.disabled"
            :title="manageAccess.reason"
            @click="openCopyRole(row)"
          >复制</el-button>
          <el-button
            v-if="manageAccess.visible && showRoleField('name') && !row.is_protected"
            link
            type="primary"
            :disabled="manageAccess.disabled"
            :title="manageAccess.reason"
            @click="openRoleNameEdit(row)"
          >编辑</el-button>
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

    <el-drawer v-model="drawerOpen" title="角色权限配置" size="min(900px, 100vw)" class="permission-editor" destroy-on-close>
      <template #header><div class="editor-title"><h2>角色权限配置 / {{ adminRoleDisplayName(selectedRole) }}</h2><p>按业务模块配置权限，保存前核对变更。</p></div></template>
      <div class="editor-context"><el-tag :type="selectedRole.status === 'active' ? 'success' : 'info'">{{ selectedRole.status === 'active' ? '启用中' : '停用中' }}</el-tag><el-tag effect="plain">{{ roleTypeLabel(selectedRole.role_type) }}</el-tag><el-tag v-if="selectedRole.is_protected" type="warning" effect="plain">受保护</el-tag><span>{{ targetTenantLabel }}</span><el-radio-group v-model="assignmentMode" size="small" :disabled="isBuiltInAdministrator"><el-radio-button value="advanced">逐项配置</el-radio-button><el-radio-button value="quick">快速分配</el-radio-button></el-radio-group></div>
      <el-alert v-if="saveError" class="role-save-error" title="保存失败" :description="saveError" type="error" :closable="false" show-icon />
      <div class="editor-workspace">
        <aside class="editor-module-rail"><h3>业务模块</h3><el-input v-model="moduleSearch" placeholder="搜索业务模块" clearable aria-label="搜索业务模块"/><nav aria-label="角色权限模块"><button v-for="menu in editorNavigation" :key="menu.key" :class="{ active: editorModule === menu.key }" @click="editorModule = menu.key"><span>{{ menu.label }}</span><small>{{ menu.count }}</small></button></nav><small class="module-rail-note">停用页面默认隐藏<br>已有授权可在历史中核对</small><el-button link type="primary" @click="editorSurface = 'history'">查看历史授权（{{ historicalPermissionCodes.length }}）</el-button></aside>
        <div class="editor-content">
          <el-select class="editor-module-mobile" v-model="editorModule" aria-label="选择业务模块"><el-option v-for="menu in editorNavigation" :key="menu.key" :label="menu.label" :value="menu.key" /></el-select>
          <el-tabs v-model="editorSurface" class="editor-tabs">
            <el-tab-pane label="菜单权限" name="menu"/><el-tab-pane label="功能操作" name="action"/><el-tab-pane label="字段权限" name="field"/><el-tab-pane label="数据范围" name="scope"/><el-tab-pane label="历史授权" name="history"/>
          </el-tabs>
          <template v-if="editorSurface === 'history'"><el-alert title="以下授权对应停用页面或已退出目录的权限，保留用于历史核对。" type="info" :closable="false"/><div v-for="code in historicalPermissionCodes" :key="code" class="historical-grant"><strong>{{ adminPermissionLabel(code) }}</strong><el-tag type="info">历史授权</el-tag><code>{{ code }}</code></div><el-empty v-if="!historicalPermissionCodes.length" description="暂无历史停用授权" :image-size="64" /></template>
          <el-form v-else-if="editorSurface === 'scope'" label-position="top" class="editor-scope">        <el-form-item label="数据范围">
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
            <el-alert
              v-if="hasPlatformDetailGrant"
              title="平台商品明细只支持按平台、国家/站点或店铺限定数据。请从仓库/供应商角色移除此页面权限，另建适用范围的角色；原角色的仓库/供应商限制请保留。"
              type="info"
              :closable="false"
              show-icon
            />
            <el-alert
              v-if="platformDetailScopeConflict"
              title="平台商品明细权限与仓库/供应商范围不能配置在同一角色。请将平台明细权限配置到只按平台、国家/站点或店铺限定的独立角色，并保留当前角色仓库/供应商范围。"
              type="warning"
              :closable="false"
              show-icon
            />
            <div v-if="scopeOptionsError" class="scope-options-error">
              <el-alert :title="scopeOptionsError" type="error" :closable="false" show-icon />
              <el-button size="small" :loading="scopeOptionsLoading" @click="loadScopeOptions">重新加载</el-button>
            </div>
            <label>
              <span>平台</span>
              <el-select v-model="roleForm.scope_config.platform_ids" :loading="scopeOptionsLoading" :disabled="scopeOptionsLoading || Boolean(scopeOptionsError)" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选平台">
                <el-option v-for="item in scopePlatforms" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>国家/站点</span>
              <el-select v-model="roleForm.scope_config.site_ids" :loading="scopeOptionsLoading" :disabled="scopeOptionsLoading || Boolean(scopeOptionsError)" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选国家或站点">
                <el-option v-for="item in scopeSites" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>店铺</span>
              <el-select v-model="roleForm.scope_config.store_ids" :loading="scopeOptionsLoading" :disabled="scopeOptionsLoading || Boolean(scopeOptionsError)" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选店铺">
                <el-option v-for="item in scopeStores" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>仓库</span>
              <el-select v-model="roleForm.scope_config.warehouse_ids" :loading="scopeOptionsLoading" :disabled="scopeOptionsLoading || Boolean(scopeOptionsError)" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选仓库">
                <el-option v-for="item in scopeWarehouses" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
            <label>
              <span>供应商</span>
              <el-select v-model="roleForm.scope_config.supplier_ids" :loading="scopeOptionsLoading" :disabled="scopeOptionsLoading || Boolean(scopeOptionsError)" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可多选供应商">
                <el-option v-for="item in scopeSuppliers" :key="item.id" :label="scopeOptionLabel(item)" :value="item.id" />
              </el-select>
            </label>
          </div>
        </el-form-item>
</el-form>
          <template v-else>
            <div class="editor-filters"><el-input v-model="permissionSearch" clearable placeholder="搜索权限名称或编码" aria-label="搜索可配置权限"/><el-checkbox v-model="onlySelected">只看已选</el-checkbox><span>已选 {{ currentSurfaceSelected }} 项</span></div>
            <section v-if="assignmentMode === 'quick'" class="editor-quick">
              <p class="editor-help">按模块选择档位；未调整的模块保留原有权限，高风险操作需逐项选择。</p>
              <div class="quick-template-row"><span>角色模板</span><el-select v-model="selectedTemplate" clearable placeholder="选择模板" @change="applyRoleTemplate"><el-option v-for="template in roleTemplates" :key="template.code" :label="template.name" :value="template.code" /></el-select></div><el-alert v-if="templateHint" :title="templateHint" type="warning" :closable="false" />
              <section v-for="menu in visibleQuickGroups" :key="menu.key" class="editor-permission-section"><h3>{{ menu.label }}</h3><div v-for="module in menu.children" :key="module.key" class="quick-module-row"><div><strong>{{ module.label }}</strong><small>{{ packageForModule(module.module)?.high_risk_codes?.length || 0 }} 项高风险权限需单独确认</small></div><el-select v-model="quickSelections[module.module]" :disabled="!manageAccess.allowed || isBuiltInAdministrator" @change="markQuickModuleTouched(module.module, $event)"><el-option v-if="quickSelections[module.module] === 'custom'" label="自定义权限（保留原配置）" value="custom" disabled/><el-option v-for="level in packageLevels" :key="level.code" :label="level.name" :value="level.code"/></el-select></div></section>
              <el-checkbox-group v-model="quickExtraPermissionCodes" :disabled="!manageAccess.allowed || isBuiltInAdministrator" class="editor-high-risk"><h3>高风险操作</h3><el-checkbox v-for="permission in visibleHighRiskPermissions" :key="permission.code" :value="permission.code" @change="markHighRiskTouched(permission.code)">{{ adminPermissionLabel(permission) }}<el-tag type="warning" size="small">需确认</el-tag></el-checkbox></el-checkbox-group>
            </section>
            <template v-else>
              <el-checkbox-group v-model="roleForm[currentSurfaceKey]" :disabled="!manageAccess.allowed || isBuiltInAdministrator" class="editor-permission-groups">
                <section v-for="menu in editorPermissionGroups" :key="menu.key" class="editor-permission-section">
                  <div v-for="item in menu.children" :key="item.key" class="editor-permission-card">
                    <div class="editor-card-heading"><div><strong>{{ item.label }}</strong><small>{{ permissionGroupDescription(item) }}</small></div><el-button link type="primary" size="small" @click="permissionDetails = permissionDetails === item.key ? '' : item.key">{{ permissionDetails === item.key ? '收起详情' : '详情' }}</el-button></div>
                    <div v-for="permission in item.permissions" :key="permission.code" class="editor-grant-row">
                      <el-checkbox :value="permission.code"><span class="editor-grant-copy"><strong>{{ adminPermissionLabel(permission) }}<el-tag v-if="isHighRiskCode(permission.code)" type="warning" size="small">高风险</el-tag></strong><small>{{ permissionDescription(permission, item) }}</small></span></el-checkbox>
                      <el-tag :type="roleForm[currentSurfaceKey].includes(permission.code) ? 'primary' : 'info'" size="small">{{ roleForm[currentSurfaceKey].includes(permission.code) ? '已选' : '未选' }}</el-tag>
                    </div>
                    <div v-if="permissionDetails === item.key" class="editor-permission-details"><span v-if="item.path">页面路径：{{ item.path }}</span><code v-for="permission in item.permissions" :key="permission.code">{{ permission.code }}</code></div>
                  </div>
                </section>
              </el-checkbox-group><el-empty v-if="!editorPermissionGroups.length" description="没有符合条件的权限" :image-size="64" />
            </template>
          </template>
        </div>
      </div>
      <template #footer><div class="editor-footer"><div><strong>本次变更</strong><span>新增 <b>{{ permissionChangeCounts.added }}</b> 项 · 移除 <b>{{ permissionChangeCounts.removed }}</b> 项</span><small v-if="pendingHighRiskPermissionCodes.length">含 {{ pendingHighRiskPermissionCodes.length }} 项高风险授权，保存时需确认</small></div><div><el-button @click="drawerOpen = false">取消</el-button><el-button v-if="manageAccess.visible" type="primary" :disabled="saveDisabled || isBuiltInAdministrator" :loading="saving" @click="saveRole">保存配置</el-button></div></div></template>
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

    <el-dialog v-model="editNameOpen" title="编辑角色名称" width="min(480px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="角色名称" required>
          <el-input v-model="editingRole.name" maxlength="120" show-word-limit @keyup.enter="submitRoleName" />
        </el-form-item>
        <el-form-item label="系统标识（不可修改）">
          <el-input :model-value="editingRole.code" readonly />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editNameOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitRoleName">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="copyOpen"
      title="复制为自定义角色"
      width="min(480px, 94vw)"
      @closed="finishCopyRole"
    >
      <el-alert
        :title="`来源角色：${adminRoleDisplayName(copySourceRole)}`"
        description="复制来源角色的可用权限和数据范围，停用权限保留在来源角色中供历史核对。新角色保存后可继续调整。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="copy-role-form">
        <el-form-item label="角色名称" required>
          <el-input v-model="copyRoleForm.name" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="系统标识" required>
          <el-input v-model="copyRoleForm.code" maxlength="80" placeholder="用于唯一识别，建议使用小写字母、数字和连字符" />
        </el-form-item>
        <el-form-item label="角色说明">
          <el-input v-model="copyRoleForm.description" maxlength="10000" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="copyOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCopyRole">复制并配置</el-button>
      </template>
    </el-dialog>
    <ResourcePolicyEditor v-model="resourcePolicyOpen" :role="resourcePolicyRole" @saved="load" />
  </AppPage>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute } from 'vue-router';
import { permissionAssignmentAvailability, buildEditorPermissionGroups, permissionChanges } from '../../utils/permissionEditor';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import ResourcePolicyEditor from '../../components/system/ResourcePolicyEditor.vue';
import {
  copyRole, createRole, deleteRole, fetchAllPermissions, fetchPermissionPackages, fetchRoleScopeOptions, fetchRoles, updateRole,
  updateRolePermissions, updateRoleStatus
} from '../../api/systemAdmin';
import { fetchResourcePolicies } from '../../api/authorization';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { adminModuleLabel, adminPermissionLabel, adminRoleDisplayName, tenantDisplayName } from '../../utils/adminDisplayLabels';
import { createRequestSequence, createSuccessfulAsyncCache } from '../../utils/asyncRequestControl';
import { buildPermissionTree, buildRegisteredMenuTree, detectMenuRegistryDrift } from '../../utils/permissionTree';
import { statusFromApiResponse } from '../../utils/uiState';
import { roleSaveErrorMessage, selectedPermissionCount } from '../../utils/rolePermissionFeedback';
import { hasPlatformDetailScopeConflict } from '../../utils/roleScopeCompatibility';

const auth = useAuthStore();
const resourcePolicyOpen = ref(false);
const resourcePolicyRole = ref(null);
const route = useRoute();
const roles = ref([]);
const permissions = ref([]);
const state = ref('loading');
const capability = ref(useMock ? 'mock' : 'pending');
const errorMessage = ref('');
const registryDrift = ref([]);
const search = ref('');
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const drawerOpen = ref(false);
const createOpen = ref(false);
const editNameOpen = ref(false);
const copyOpen = ref(false);
const saving = ref(false);
const saveError = ref('');
const selectedRole = ref({});
const copySourceRole = ref({});
const pendingCopiedRole = ref(null);
const targetTenant = ref(null);
const assignmentMode = ref('advanced');
const editorModule = ref('all'), moduleSearch = ref(''), permissionSearch = ref(''), onlySelected = ref(false), editorSurface = ref('action'), permissionDetails = ref('');
const packageCatalog = ref([]);
const permissionCatalogError = ref('');
const permissionDirectoryCache = createSuccessfulAsyncCache(
  fetchAllPermissions,
  (result) => Boolean(result?.response?.success),
);
const permissionPackageCache = createSuccessfulAsyncCache(
  fetchPermissionPackages,
  (result) => Boolean(result?.success),
);
const roleLoads = createRequestSequence();
const scopeOptionLoads = createRequestSequence();
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
const editingRole = reactive({ id: null, name: '', originalName: '', code: '' });
const copyRoleForm = reactive({ name: '', code: '', description: '' });
const scopePlatforms = ref([]);
const scopeSites = ref([]);
const scopeStores = ref([]);
const scopeWarehouses = ref([]);
const scopeSuppliers = ref([]);
const scopeOptionsLoading = ref(false);
const scopeOptionsError = ref('');
const legacyScopeType = ref('');
// Keep custom business scope while the editor temporarily switches to the
// all-scope template. The API contract forbids sending custom keys for all.
const preservedCustomScopeConfig = ref({});
const manageAccess = computed(() => {
  const actionAccess = getActionAccess(auth, { permission: 'system.roles.manage' });
  const allScopeAllowed = auth.hasAllDataScopeFor('system.roles.manage');
  return {
    ...actionAccess,
    allowed: actionAccess.allowed && allScopeAllowed,
    disabled: actionAccess.disabled || !allScopeAllowed,
    reason: actionAccess.allowed && !allScopeAllowed
      ? '角色管理需要“租户内全部数据”范围'
      : actionAccess.reason,
  };
});
const isBuiltInAdministrator = computed(() => selectedRole.value?.code === 'administrator');
const saveDisabled = computed(() => (
  !manageAccess.value.allowed
  || saving.value
  || (roleForm.scope_type === 'custom' && (scopeOptionsLoading.value || Boolean(scopeOptionsError.value)))
));
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
const registeredMenuTree = computed(() => buildRegisteredMenuTree());
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
  return menu.children.reduce((count, item) => count + (item.permissions?.length || 0), 0);
}

function permissionTreeForSurface(type) { return buildEditorPermissionGroups({permissions:permissions.value,menuTree:registeredMenuTree.value,moduleTree:permissionTree.value,type,unavailable:unavailablePermissionCodes.value}); }

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
const unavailablePermissionCodes = computed(() => permissionAssignmentAvailability(permissions.value, registeredMenuTree.value, auth.currentUser?.module_statuses || {}));
const historicalPermissionCodes = computed(() => { const available = new Set(permissions.value.map(p => p.code)); return originalPermissionCodes.value.filter(code => !available.has(code) || unavailablePermissionCodes.value.has(code)); });
const currentSurfaceKey = computed(() => permissionSurfaces.find(surface => surface.type === editorSurface.value)?.key || 'action_permission_codes');
const currentSurfaceSelected = computed(() => assignmentMode.value === 'quick' ? candidatePermissionCodes.value.length : (roleForm[currentSurfaceKey.value]?.length || 0));
const availableQuickTree = computed(() => {
  const activeGroups = permissionTreeForSurface('action');
  const claimed = new Set();
  return activeGroups.map(group => ({ ...group, children: packageCatalog.value.filter(item => !claimed.has(item.module) && group.children.some(page => page.permissions.some(permission => permission.module === item.module))).map(item => { claimed.add(item.module); return { key: `quick:${item.module}`, module: item.module, label: adminModuleLabel(item.module) }; }) })).filter(group => group.children.length);
});
const editorNavigation = computed(() => { const tree = assignmentMode.value === 'quick' ? availableQuickTree.value : permissionTreeForSurface(['menu','action','field'].includes(editorSurface.value) ? editorSurface.value : 'action'); const rows=tree.map(menu => ({key:menu.key,label:menu.label,count:menu.children.reduce((sum,item)=>sum+(item.permissions?.length || 1),0)})); return [{key:'all',label:'全部模块',count:rows.reduce((sum,row)=>sum+row.count,0)},...rows].filter(row=>!moduleSearch.value || row.label.includes(moduleSearch.value.trim())); });
watch(editorSurface,()=>{permissionDetails.value='';});
const matchesPermission = permission => (!permissionSearch.value.trim() || `${adminPermissionLabel(permission)} ${permission.code}`.toLowerCase().includes(permissionSearch.value.trim().toLowerCase())) && (!onlySelected.value || candidatePermissionCodes.value.includes(permission.code));
const editorPermissionGroups = computed(() => permissionTreeForSurface(editorSurface.value).filter(menu=>editorModule.value==='all'||menu.key===editorModule.value).map(menu=>({...menu,children:menu.children.map(item=>({...item,permissions:item.permissions.filter(matchesPermission)})).filter(item=>item.permissions.length)})).filter(menu=>menu.children.length));
const visibleQuickGroups = computed(()=>availableQuickTree.value.filter(menu=>editorModule.value==='all'||menu.key===editorModule.value).map(menu=>({...menu,children:menu.children.filter(module=>!permissionSearch.value || module.label.includes(permissionSearch.value.trim())).filter(module=>!onlySelected.value||quickSelections[module.module]!=='none')})).filter(menu=>menu.children.length));
const visibleHighRiskPermissions = computed(()=>{const modules=new Set(visibleQuickGroups.value.flatMap(menu=>menu.children.map(module=>module.module)));return highRiskPermissions.value.filter(permission=>modules.has(permission.module)&&!unavailablePermissionCodes.value.has(permission.code)&&matchesPermission(permission));});
function isHighRiskCode(code) { return highRiskPermissions.value.some(permission=>permission.code===code); }
function permissionGroupDescription(item) { return `${item.label}的访问与操作权限`; }
function permissionDescription(permission, item) {
  if (editorSurface.value === 'menu') return `在导航中显示${item.label}入口`;
  if (editorSurface.value === 'field') return '控制该字段在业务页面中的显示';
  const action = (permission.action || permission.code).split('.').at(-1);
  return ({ view: `查看${item.label}的业务信息`, manage: `维护${item.label}的业务信息`, import: `导入${item.label}数据`, export: `导出${item.label}数据`, download: `下载${item.label}资料`, approve: `审批${item.label}中的业务申请`, review: `审核${item.label}中的业务记录` })[action] || `允许执行${adminPermissionLabel(permission)}`;
}
const permissionChangeCounts = computed(() => permissionChanges(originalPermissionCodes.value, candidatePermissionCodes.value));

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

function quickDraftCodes() {
  const touched=quickTouchedModules.value;
  const touchedCodes=packageCatalog.value.flatMap(item=>touched.has(item.module)?(item.levels?.[quickSelections[item.module] || 'none'] || []):[]);
  const untouched=roleForm.permission_codes.filter(code=>!touched.has(permissionModuleForCode(code)));
  const extra=quickExtraPermissionCodes.value.filter(code=>touched.has(permissionModuleForCode(code)));
  return [...new Set([...touchedCodes,...untouched,...extra].filter(code=>!unavailablePermissionCodes.value.has(code)).concat(historicalPermissionCodes.value))];
}
watch(assignmentMode,(mode,previous)=>{
  const codes=previous==='quick' ? quickDraftCodes() : [...new Set([...roleForm.menu_permission_codes,...roleForm.action_permission_codes,...roleForm.field_permission_codes])];
  roleForm.permission_codes=codes;
  permissionSearch.value=''; onlySelected.value=false; editorModule.value='all';
  if(mode==='quick') inferQuickSelection({permission_codes:codes});
  else {roleForm.menu_permission_codes=codes.filter(code=>code.startsWith('menu.'));roleForm.field_permission_codes=codes.filter(code=>code.startsWith('field.'));roleForm.action_permission_codes=codes.filter(code=>!code.startsWith('menu.')&&!code.startsWith('field.'));}
});
const candidatePermissionCodes = computed(() => {
  if (assignmentMode.value !== 'quick') {
    return [...new Set([
      ...roleForm.menu_permission_codes,
      ...roleForm.action_permission_codes,
      ...roleForm.field_permission_codes,
      ...historicalPermissionCodes.value,
    ])];
  }
  return quickDraftCodes();
});

const hasPlatformDetailGrant = computed(() => candidatePermissionCodes.value.some((code) => [
  'menu.listings.products_platform_details.view',
  'listings.product_detail.view',
  'listings.product_detail.manage',
  'listings.product_detail.import',
].includes(code)));
const platformOverrideKnownValid = ref(false);
const platformDetailScopeConflict = computed(() => hasPlatformDetailScopeConflict(
  candidatePermissionCodes.value,
  roleForm.scope_config,
)
  && !platformOverrideKnownValid.value);

const pendingHighRiskPermissionCodes = computed(() => {
  const original = new Set(originalPermissionCodes.value);
  const highRiskCodes = new Set(highRiskPermissions.value.map((permission) => permission.code));
  return candidatePermissionCodes.value.filter((code) => highRiskCodes.has(code) && !original.has(code));
});

const pendingHighRiskSummary = computed(() => pendingHighRiskPermissionCodes.value
  .map((code) => adminPermissionLabel(code))
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
    quickSelections[item.module] = level ? level[0] : (roleCodes.size ? 'custom' : 'none');
  }
  quickExtraPermissionCodes.value = (role?.permission_codes || []).filter((code) => highRisk.has(code));
}

async function applyRoleTemplate(templateCode) {
  const template = roleTemplates.find((item) => item.code === templateCode);
  if (!template) return;
  const currentScopeType = roleForm.scope_type;
  const currentScopeConfig = Object.fromEntries(
    Object.entries(roleForm.scope_config || {}).map(([key, values]) => [key, Array.isArray(values) ? [...values] : values]),
  );
  if ((currentScopeType === 'custom' || legacyScopeType.value) && template.scope_type === 'all') {
    if (currentScopeType === 'custom') preservedCustomScopeConfig.value = cloneScopeConfig(currentScopeConfig);
    try {
      await ElMessageBox.confirm(
        '此模板使用“租户内全部数据”范围。确认后将扩大当前角色的数据可见范围；已有业务范围会暂存，切回“按业务范围限制”时可恢复。',
        '确认扩大数据范围',
        { type: 'warning', confirmButtonText: '确认扩大', cancelButtonText: '保留当前范围' },
      );
    } catch {
      selectedTemplate.value = '';
      return;
    }
  }
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
  // Applying a template must not silently erase an existing custom scope.
  // A custom template keeps the current selection; an all-scope template has
  // already received an explicit confirmation above.
  roleForm.scope_config = roleForm.scope_type === 'custom'
    ? cloneScopeConfig(currentScopeType === 'custom' ? currentScopeConfig : preservedCustomScopeConfig.value)
    : {};
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
  const loadToken = roleLoads.begin();
  state.value = 'loading';
  errorMessage.value = '';
  const tenantParams = targetTenantId.value ? { tenant_id: targetTenantId.value } : {};
  // The role table is the primary page content. Start metadata loading in the
  // background, but do not make a slow permission catalog block the first row.
  void loadPermissionCatalog(tenantParams);
  const roleResponse = await fetchRoles({ ...tenantParams, search: search.value.trim(), page: page.value, page_size: pageSize });
  if (!loadToken.isCurrent()) return;
  if (!roleResponse.success) {
    const failed = roleResponse;
    state.value = statusFromApiResponse(failed, navigator.onLine);
    errorMessage.value = failed.message;
    capability.value = responseCapability(failed);
    return;
  }
  roles.value = unpack(roleResponse);
  total.value = Number.isFinite(roleResponse.data?.count) ? roleResponse.data.count : roles.value.length;
  targetTenant.value = roleResponse.data?.tenant || targetTenant.value || {
    id: targetTenantId.value || auth.currentUser?.tenant_id,
    name: targetTenantId.value ? '' : '当前租户',
    code: '',
  };
  capability.value = responseCapability(roleResponse);
  state.value = roles.value.length ? 'ready' : 'empty';
}

async function loadPermissionDirectory() {
  let result;
  try {
    result = await permissionDirectoryCache.get('global');
  } catch (error) {
    return { response: { success: false, message: error?.message || '权限目录加载失败' }, rows: [] };
  }
  if (!result?.response?.success) {
    return result;
  }
  permissions.value = result.rows;
  registryDrift.value = detectMenuRegistryDrift({ permissions: permissions.value });
  return result;
}

async function loadPermissionPackages(tenantParams) {
  const key = String(tenantParams.tenant_id || 'current');
  return permissionPackageCache.get(key, tenantParams);
}

async function loadPermissionCatalog(tenantParams) {
  const key = String(tenantParams.tenant_id || 'current');
  let directoryResult;
  let packageResponse;
  try {
    [directoryResult, packageResponse] = await Promise.all([
      loadPermissionDirectory(),
      loadPermissionPackages(tenantParams),
    ]);
  } catch (error) {
    if (key === String(targetTenantId.value || 'current')) {
      permissionCatalogError.value = error?.message || '权限目录加载失败';
    }
    return { directoryResult, packageResponse };
  }
  const currentKey = String(targetTenantId.value || 'current');
  if (key !== currentKey) return { directoryResult, packageResponse };
  if (directoryResult?.response?.success && packageResponse?.success) {
    packageCatalog.value = packageResponse.data?.packages || [];
    packageLevels.value = packageResponse.data?.levels || packageLevels.value;
    permissionCatalogError.value = '';
  } else {
    permissionCatalogError.value = directoryResult?.response?.message
      || packageResponse?.message
      || '权限目录加载失败';
  }
  return { directoryResult, packageResponse };
}
function searchRoles() {
  page.value = 1;
  load();
}
function openResourcePolicies(role) {
  if (!manageAccess.value.allowed) return;
  resourcePolicyRole.value = role;
  resourcePolicyOpen.value = true;
}

watch(targetTenantId, () => {
  page.value = 1;
  targetTenant.value = null;
  load();
});
async function openRole(role) {
  // A drawer opened while the background preload is still pending must wait
  // for the same in-flight requests, so its selections are never inferred
  // from a partially loaded catalog.
  const tenantKey = String(targetTenantId.value || 'current');
  const catalog = await loadPermissionCatalog(targetTenantId.value ? { tenant_id: targetTenantId.value } : {});
  if (tenantKey !== String(targetTenantId.value || 'current')) return;
  if (!catalog.directoryResult?.response?.success || !catalog.packageResponse?.success) {
    ElMessage.error(permissionCatalogError.value || '权限目录加载失败，请稍后重试');
    return;
  }
  selectedRole.value = role;
  platformOverrideKnownValid.value = false;
  const resourcePoliciesResponse = await fetchResourcePolicies(role.id);
  if (resourcePoliciesResponse?.success) {
    platformOverrideKnownValid.value = (resourcePoliciesResponse.data?.policies || []).some((policy) => {
      if (policy.resource_code !== 'platform_product_details' || policy.permission_code !== '*' || policy.scope_type !== 'custom') return false;
      const config = policy.config || {};
      const allowedKeys = new Set(['platform_ids', 'site_ids', 'store_ids']);
      const entries = Object.entries(config);
      return entries.length > 0 && entries.every(([key, values]) => allowedKeys.has(key) && Array.isArray(values) && values.length > 0);
    });
  }
  saveError.value = '';
  originalPermissionCodes.value = [...new Set(role.permission_codes || [])];
  assignmentMode.value = 'advanced';
  editorModule.value='all'; editorSurface.value='action'; permissionSearch.value=''; moduleSearch.value=''; onlySelected.value=false; permissionDetails.value='';
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
  preservedCustomScopeConfig.value = roleForm.scope_type === 'custom' || isLegacy
    ? cloneScopeConfig(savedConfig)
    : {};
  if (roleForm.scope_type === 'custom') ensureCustomScopeShape();
  const surfaceGroups=permissionTreeForSurface('action');
  const relevant=surfaceGroups.find(menu=>menu.children.some(item=>item.permissions.some(permission=>originalPermissionCodes.value.includes(permission.code))));
  editorModule.value=relevant?.key || surfaceGroups[0]?.key || 'all';
  drawerOpen.value = true;
  loadScopeOptions();
}

function copyRoleCode(source) {
  const normalized = String(source?.code || 'role')
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^[-_]+|[-_]+$/g, '') || 'role';
  const base = normalized.replace(/-copy(?:-\d+)?$/, '') || 'role';
  const existingCodes = new Set(roles.value.map((role) => role.code));
  for (let index = 1; index < 1000; index += 1) {
    const suffix = index === 1 ? '-copy' : `-copy-${index}`;
    const candidate = `${base.slice(0, 80 - suffix.length)}${suffix}`;
    if (!existingCodes.has(candidate)) return candidate;
  }
  const suffix = `-${Date.now().toString(36)}`;
  return `${base.slice(0, 80 - suffix.length)}${suffix}`;
}

function copyRoleName(source) {
  const base = `${source?.name || '角色'} 副本`;
  const existingNames = new Set(roles.value.map((role) => role.name));
  if (!existingNames.has(base)) return base.slice(0, 100);
  for (let index = 2; index < 1000; index += 1) {
    const suffix = ` ${index}`;
    const candidate = `${base.slice(0, 100 - suffix.length)}${suffix}`;
    if (!existingNames.has(candidate)) return candidate;
  }
  return base.slice(0, 100);
}

function openCopyRole(role) {
  if (!manageAccess.value.allowed) {
    ElMessage.warning(manageAccess.value.reason);
    return;
  }
  copySourceRole.value = role;
  copyRoleForm.name = copyRoleName(role);
  copyRoleForm.code = copyRoleCode(role);
  copyRoleForm.description = role?.description || '';
  copyOpen.value = true;
}

function ensureCustomScopeShape() {
  const current = roleForm.scope_config || {};
  roleForm.scope_config = Object.fromEntries(
    BUSINESS_SCOPE_KEYS.map((key) => [key, Array.isArray(current[key]) ? [...current[key]] : []]),
  );
}

function cloneScopeConfig(config) {
  return Object.fromEntries(
    Object.entries(config || {}).map(([key, values]) => [key, Array.isArray(values) ? [...values] : values]),
  );
}

function onScopeTypeChange(value) {
  if (value !== 'custom' && Object.keys(roleForm.scope_config || {}).length) {
    preservedCustomScopeConfig.value = cloneScopeConfig(roleForm.scope_config);
  }
  legacyScopeType.value = '';
  if (value === 'custom') {
    roleForm.scope_config = cloneScopeConfig(preservedCustomScopeConfig.value);
    ensureCustomScopeShape();
  }
  else roleForm.scope_config = {};
}

async function loadScopeOptions() {
  const loadToken = scopeOptionLoads.begin();
  scopeOptionsLoading.value = true;
  scopeOptionsError.value = '';
  scopePlatforms.value = [];
  scopeSites.value = [];
  scopeStores.value = [];
  scopeWarehouses.value = [];
  scopeSuppliers.value = [];
  try {
    const response = await fetchRoleScopeOptions(targetTenantId.value ? { tenant_id: targetTenantId.value } : {});
    if (!loadToken.isCurrent()) return;
    if (!response?.success) {
      scopeOptionsError.value = response?.message || '业务范围选项加载失败，请重试。';
      return;
    }
    scopePlatforms.value = response.data?.platforms || [];
    scopeSites.value = response.data?.sites || [];
    scopeStores.value = response.data?.stores || [];
    scopeWarehouses.value = response.data?.warehouses || [];
    scopeSuppliers.value = response.data?.suppliers || [];
  } catch (error) {
    if (loadToken.isCurrent()) scopeOptionsError.value = error?.message || '业务范围选项加载失败，请重试。';
  } finally {
    if (loadToken.isCurrent()) scopeOptionsLoading.value = false;
  }
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
  if (roleForm.scope_type === 'custom' && (scopeOptionsLoading.value || scopeOptionsError.value)) {
    ElMessage.warning(scopeOptionsLoading.value ? '业务范围选项正在加载，请稍后保存。' : '请先重新加载业务范围选项。');
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
    if (hasPlatformDetailScopeConflict(candidatePermissionCodes.value, scopeConfig) && !platformOverrideKnownValid.value) {
      ElMessage.warning('平台商品明细不能按仓库或供应商授权。请将该页面权限放入只按平台、站点或店铺限定的独立角色。');
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
  saveError.value = '';
  saving.value = true;
  const permissionCodes = [
    ...new Set([
      ...roleForm.menu_permission_codes,
      ...roleForm.action_permission_codes,
      ...roleForm.field_permission_codes,
      ...historicalPermissionCodes.value,
    ]),
  ];
  const payload = { ...roleForm, permission_codes: candidatePermissionCodes.value,
    assignment_mode: assignmentMode.value,
    confirmed_high_risk_permission_codes: assignmentMode.value === 'quick' ? candidatePermissionCodes.value.filter(isHighRiskCode) : [],
    menu_permission_codes: candidatePermissionCodes.value.filter(code => permissions.value.find(permission=>permission.code===code)?.permission_type === 'menu' || code.startsWith('menu.')),
    field_permission_codes: candidatePermissionCodes.value.filter(code => permissions.value.find(permission=>permission.code===code)?.permission_type === 'field' || code.startsWith('field.')),
    action_permission_codes: candidatePermissionCodes.value.filter(code => !code.startsWith('menu.') && !code.startsWith('field.')),
    scope_config: scopeConfig };

  let response;
  try {
    response = await updateRolePermissions(
      selectedRole.value.id,
      payload,
      targetTenantId.value || undefined,
    );
  } catch (error) {
    response = { success: false, message: error?.message || '保存失败' };
  } finally {
    saving.value = false;
  }
  if (!response?.success) {
    saveError.value = roleSaveErrorMessage(response);
    return ElMessage.error({ message: `保存失败：${saveError.value}`, duration: 6000, showClose: true });
  }
  ElMessage.success('角色权限已保存并记录审计');
  const refreshResponse = await auth.refreshCurrentUser();
  if (!refreshResponse?.success) ElMessage.warning('角色已保存，但当前会话权限刷新失败，请稍后重试');
  drawerOpen.value = false;
  await load();
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
    const refreshResponse = await auth.refreshCurrentUser();
    if (!refreshResponse?.success) ElMessage.warning('角色状态已更新，但当前会话权限刷新失败，请稍后重试');
    await load();
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
    const refreshResponse = await auth.refreshCurrentUser();
    if (!refreshResponse?.success) ElMessage.warning('角色已删除，但当前会话权限刷新失败，请重新加载或稍后重试。');
    await load();
  } catch (error) {
    if (error === 'cancel' || error === 'close') return;
    ElMessage.error(error?.message || '角色删除失败');
  }
}

function openRoleNameEdit(row) {
  if (!manageAccess.value.allowed || row.is_protected) return;
  editingRole.id = row.id;
  editingRole.name = row.name || '';
  editingRole.originalName = row.name || '';
  editingRole.code = row.code || '';
  editNameOpen.value = true;
}

async function submitRoleName() {
  if (!manageAccess.value.allowed) {
    ElMessage.warning(manageAccess.value.reason);
    return;
  }
  const name = editingRole.name.trim();
  if (!name) return ElMessage.warning('请填写角色名称');
  if (name === editingRole.originalName) {
    editNameOpen.value = false;
    return;
  }
  saving.value = true;
  const response = await updateRole(editingRole.id, { name }, targetTenantId.value || undefined);
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '角色名称保存失败');
  ElMessage.success('角色名称已更新');
  editNameOpen.value = false;
  load();
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

async function submitCopyRole() {
  if (!manageAccess.value.allowed) {
    ElMessage.warning(manageAccess.value.reason);
    return;
  }
  const name = copyRoleForm.name.trim();
  const code = copyRoleForm.code.trim();
  if (!name || !code) return ElMessage.warning('请填写角色名称和系统标识');
  saving.value = true;
  const response = await copyRole(
    copySourceRole.value.id,
    { name, code, description: copyRoleForm.description.trim() },
    targetTenantId.value || undefined,
  );
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '角色复制失败');
  pendingCopiedRole.value = {
    ...copySourceRole.value,
    ...(response.data || {}),
    name,
    code,
    role_type: 'custom',
    is_protected: false,
    status: 'active',
  };
  copyOpen.value = false;
  ElMessage.success('角色已复制，可继续调整权限');
  await load();
}

function finishCopyRole() {
  const copiedRole = pendingCopiedRole.value;
  pendingCopiedRole.value = null;
  copySourceRole.value = {};
  copyRoleForm.name = '';
  copyRoleForm.code = '';
  copyRoleForm.description = '';
  if (copiedRole?.id) openRole(copiedRole);
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
.role-system-code { color: #475569; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 12px; }
.role-heading strong, .role-heading span { display: block; }
.copy-role-form { margin-top: 16px; }
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
.permission-tree__selected-count { margin-left: 10px; padding: 2px 8px; border-radius: 999px; color: #1677ff; background: #eaf3ff; font-size: 11px; line-height: 18px; white-space: nowrap; }
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
.role-save-error { margin-bottom: 16px; }
.scope-options-error { display: grid; gap: 8px; }
.scope-options-error .el-button { justify-self: start; }
@media (max-width: 980px) { .access-layers { grid-template-columns: repeat(3, 1fr); } .access-layer:nth-child(3) { border-right: 0; } .access-layer:nth-child(-n + 3) { border-bottom: 1px solid #e5eaf0; } }
@media (max-width: 640px) { .access-layers { grid-template-columns: repeat(2, 1fr); } .access-layer:nth-child(3) { border-right: 1px solid #e5eaf0; } .access-layer:nth-child(even) { border-right: 0; } .permission-tree__module, .permission-tree__module--advanced { grid-template-columns: 1fr; } .permission-tree__items { grid-template-columns: 1fr; } .permission-surface__heading { display: grid; gap: 4px; } .matrix-toolbar { grid-template-columns: 1fr auto; } .matrix-toolbar span { display: none; } }

.permission-guide { margin-bottom:16px;color:#64748b;font-size:13px; }.permission-guide summary { cursor:pointer; }.permission-guide .access-layers { margin-top:12px; }
.editor-title h2 { margin:0;font-size:22px;color:#14213b;line-height:1.4; }.editor-title p { margin:8px 0 0;font-size:14px;color:#73839a; }.editor-context { display:flex;align-items:center;gap:8px;margin-bottom:22px;flex-wrap:wrap; }.editor-context>span {color:#64748b;font-size:13px;}.editor-context .el-radio-group {margin-left:auto;}
.editor-workspace {display:grid;grid-template-columns:215px minmax(0,1fr);border-top:1px solid #e4eaf3;min-height:550px;}.editor-module-rail {padding:22px 20px 20px 0;border-right:1px solid #e4eaf3;min-width:0;}.editor-module-rail h3 {font-size:15px;margin:0 0 12px;color:#172033;}.editor-module-rail nav {display:grid;gap:4px;margin:16px 0;}.editor-module-rail nav button {display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:42px;background:transparent;border:0;border-radius:5px;padding:10px 12px;text-align:left;color:#485875;cursor:pointer;font-size:14px;}.editor-module-rail nav button.active {background:#edf3ff;color:#2463eb;font-weight:600;}.editor-module-rail nav small {color:#8a99af;font-size:12px;}.module-rail-note {display:block;color:#8a99af;line-height:1.7;margin:16px 0 8px;}.editor-content {padding:8px 0 22px 24px;min-width:0;}.editor-module-mobile {display:none;}.editor-tabs {margin-bottom:18px;}.editor-tabs :deep(.el-tabs__item) {padding:0 15px;font-size:14px;}.editor-filters {display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap;}.editor-filters .el-input {flex:1;min-width:180px;}.editor-filters>span {font-size:12px;color:#73839a;}.editor-permission-groups {display:block;}.editor-permission-section {border:1px solid #e4eaf3;border-radius:7px;margin-bottom:16px;overflow:hidden;}.editor-permission-section h3 {margin:0;padding:13px 16px;font-size:14px;font-weight:600;background:#f8faff;border-bottom:1px solid #e4eaf3;color:#14213b;}.editor-permission-row {padding:14px 16px;display:grid;grid-template-columns:minmax(120px,0.8fr) minmax(0,2fr);gap:16px;border-bottom:1px solid #edf1f6;}.editor-permission-row:last-child {border-bottom:0;}.editor-permission-label {display:grid;align-content:start;justify-items:start;gap:5px;}.editor-permission-label strong {font-size:14px;font-weight:500;line-height:1.6;color:#334155;}.editor-permission-options {display:flex;flex-wrap:wrap;gap:10px 22px;min-width:0;}.editor-permission-options .el-checkbox {height:auto;min-height:30px;margin:0;max-width:100%;}.editor-permission-options :deep(.el-checkbox__label) {white-space:normal;overflow-wrap:anywhere;font-size:13px;line-height:1.5;}.editor-permission-options .el-tag {margin-left:6px;}.editor-permission-details {grid-column:1/-1;display:grid;gap:6px;padding:12px;background:#f8faff;color:#73839a;font-size:12px;overflow-wrap:anywhere;}.editor-help {font-size:13px;color:#73839a;line-height:1.7;}.quick-module-row {display:grid;grid-template-columns:1fr 160px;gap:16px;align-items:center;padding:14px 16px;border-bottom:1px solid #edf1f6;}.quick-module-row>div {display:grid;gap:6px;}.quick-module-row strong {font-size:14px;}.quick-module-row small {font-size:12px;color:#8a99af;}.editor-high-risk {display:grid;gap:12px;}.editor-high-risk h3 {font-size:14px;}.editor-high-risk .el-checkbox {height:auto;margin:0;}.editor-high-risk :deep(.el-checkbox__label) {white-space:normal;}.editor-scope {padding:4px 0;}.editor-scope :deep(.el-alert) {margin-bottom:14px;}.historical-grant {display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:16px 0;border-bottom:1px solid #edf1f6;}.historical-grant strong {font-size:14px;}.historical-grant code {width:100%;font-size:12px;color:#73839a;overflow-wrap:anywhere;}.editor-footer {display:flex;justify-content:space-between;align-items:center;gap:16px;text-align:left;padding-top:12px;border-top:1px solid #e4eaf3;}.editor-footer>div:first-child {display:flex;align-items:center;gap:12px;flex-wrap:wrap;}.editor-footer strong {font-size:14px;color:#24334f;}.editor-footer span {font-size:13px;color:#73839a;}.editor-footer b {color:#2463eb;font-weight:500;}.editor-footer small {font-size:12px;color:#b7791f;}.editor-footer>div:last-child {flex-shrink:0;}.editor-module-rail button:focus-visible {outline:2px solid #2463eb;outline-offset:2px;}
@media(max-width:760px){.editor-workspace{display:block;min-height:0;}.editor-module-rail{display:none;}.editor-content{padding:12px 0;}.editor-module-mobile{display:block;width:100%;margin-bottom:12px;}.editor-title h2{font-size:18px;}.editor-permission-row{grid-template-columns:1fr;gap:10px;}.editor-footer{flex-wrap:wrap;}.editor-footer>div:last-child{margin-left:auto;}.editor-context .el-radio-group{margin-left:0;}.editor-tabs :deep(.el-tabs__item){padding:0 9px;font-size:13px;}.quick-module-row{grid-template-columns:1fr;}.editor-filters .el-input{min-width:100%;}.editor-scope :deep(.el-radio-group){display:flex;flex-wrap:wrap;gap:8px;}}

:global(.permission-editor .el-drawer__header) {margin-bottom:12px;padding:24px 24px 0;}
:global(.permission-editor .el-drawer__body) {padding:12px 24px 0;}
.editor-permission-groups {font-size:14px;line-height:1.5;}
.editor-context {margin-bottom:14px;}
.editor-permission-groups .editor-permission-section {border:0;border-radius:0;overflow:visible;}
.editor-permission-card {border:1px solid #e1e8f3;border-radius:7px;margin-bottom:18px;overflow:hidden;}
.editor-card-heading {display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 18px;background:#f5f8fc;border-bottom:1px solid #e1e8f3;}
.editor-card-heading strong {font-size:16px;color:#172640;}
.editor-card-heading small {display:block;margin-top:5px;font-size:13px;color:#7b8aa3;}
.editor-grant-row {display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:76px;padding:14px 18px;border-bottom:1px solid #e9edf5;}
.editor-grant-row:last-child {border-bottom:0;}
.editor-grant-row .el-checkbox {height:auto;min-width:0;flex:1;margin:0;}
.editor-grant-row :deep(.el-checkbox__label) {white-space:normal;min-width:0;padding-left:14px;}
.editor-grant-copy {display:block;}
.editor-grant-copy strong {display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:16px;line-height:1.5;color:#24344f;}
.editor-grant-copy small {display:block;margin-top:5px;color:#7c8ba3;font-size:14px;line-height:1.5;}
.editor-grant-row>.el-tag {flex-shrink:0;}
@media(max-width:760px) {:global(.permission-editor .el-drawer__header){padding:18px 16px 0;}:global(.permission-editor .el-drawer__body){padding:8px 16px 0;}.editor-card-heading{padding:12px;}.editor-grant-row{padding:12px;gap:8px;}.editor-grant-row :deep(.el-checkbox__label){padding-left:10px;}.editor-grant-copy strong{font-size:14px;}.editor-grant-copy small{font-size:13px;}}
</style>
