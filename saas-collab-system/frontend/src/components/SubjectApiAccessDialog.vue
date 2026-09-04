<template>
  <el-dialog
    v-model="dialogVisible"
    width="min(920px, 94vw)"
    class="subject-api-dialog"
    append-to-body
    destroy-on-close
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    @opened="load"
  >
    <template #header>
      <div class="dialog-title">
        <h2>{{ row?.name || row?.code }} · API 接入</h2>
        <p>{{ subtitle }}</p>
      </div>
    </template>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert
      v-if="historyError"
      :title="historyError"
      type="warning"
      :closable="false"
      show-icon
    />
    <section v-if="authorizationUrl" class="authorization-url-fallback" aria-label="平台授权地址兜底">
      <el-alert
        title="浏览器未能打开授权新窗口，请复制下方已校验的授权地址到新标签页继续。"
        type="warning"
        :closable="false"
        show-icon
      />
      <div class="authorization-url-row">
        <el-input
          :model-value="authorizationUrl"
          readonly
          aria-label="平台授权地址"
        />
        <el-button type="primary" @click="copyAuthorizationUrl">复制授权地址</el-button>
      </div>
    </section>
    <el-skeleton v-if="loading" :rows="7" animated />

    <template v-else-if="access">
      <section class="subject-summary" aria-label="业务主体摘要">
        <div><span>档案编码</span><strong>{{ access.subject.code || '—' }}</strong></div>
        <div><span>国家/站点</span><strong>{{ access.subject.country_code || '—' }}</strong></div>
        <div><span>令牌策略</span><strong>{{ tokenPolicyLabel }}</strong></div>
      </section>

      <div class="access-list">
        <section v-for="apiType in access.api_types" :key="apiType" class="access-section">
          <div class="section-heading">
            <div>
              <h3>{{ apiLabels[apiType] }}</h3>
              <p>{{ apiDescriptions[apiType] }}</p>
            </div>
            <el-tag :type="activeBindings(apiType).length ? 'success' : 'info'" effect="light">
              {{ bindingStatus(apiType) }}
            </el-tag>
          </div>

          <div v-if="isMultipleAdvertising(apiType)" class="advertiser-list">
            <article v-for="binding in activeBindings(apiType)" :key="binding.id" class="advertiser-binding">
              <div class="advertiser-heading">
                <div><span>广告户 ID</span><strong>{{ binding.platform_store_id || '—' }}</strong></div>
                <el-tag type="success" effect="light">{{ statusLabel(binding.status) }}</el-tag>
              </div>
              <div class="binding-grid">
                <div><span>接入配置</span><strong>{{ binding.account_alias || '—' }}</strong></div>
                <div><span>授权时间</span><strong>{{ formatDate(binding.authorized_at) }}</strong></div>
                <div><span>最近同步</span><strong>{{ formatDate(binding.last_run_at) }}</strong></div>
              </div>
              <div class="section-actions">
                <el-button @click="openAuthorizationDetail(binding)">授权详情</el-button>
                <el-button
                  v-if="storeSyncCreateAccess.visible"
                  :disabled="storeSyncActionDisabled(apiType, binding)"
                  :title="storeSyncActionTitle(apiType, binding)"
                  @click="createStoreSyncJob(apiType, binding)"
                >创建同步任务</el-button>
                <el-button
                  v-if="storeRefreshAccess.visible"
                  :loading="busy === `refresh-${binding.id}`"
                  :disabled="storeRefreshAccess.disabled"
                  :title="storeRefreshAccess.reason"
                  @click="refreshStoreBinding(binding)"
                >刷新令牌</el-button>
                <el-button
                  v-if="readonlyCheckAccess.visible"
                  :loading="busy === `check-${binding.id}`"
                  :disabled="readonlyCheckAccess.disabled || !binding.integration_config_id"
                  :title="readonlyCheckAccess.disabled ? readonlyCheckAccess.reason : '调用一次平台只读接口，不会刷新或替换 Token'"
                  @click="checkToken(binding)"
                >平台只读检查</el-button>
                <el-button
                  v-if="storeRevokeAccess.visible"
                  :loading="busy === `disable-${binding.id}`"
                  :disabled="storeRevokeAccess.disabled"
                  :title="storeRevokeAccess.reason"
                  @click="disableStoreBinding(binding)"
                >撤销广告户授权</el-button>
              </div>
            </article>
          </div>

          <div v-else-if="primaryBinding(apiType)" class="binding-grid is-primary">
            <div><span>接入配置</span><strong>{{ primaryBinding(apiType).account_alias || '—' }}</strong></div>
            <div v-if="subjectType === 'store'">
              <span>{{ apiType === 'advertising' ? '广告账户 ID' : '平台店铺 ID' }}</span>
              <strong>{{ primaryBinding(apiType).platform_store_id || '—' }}</strong>
            </div>
            <div><span>授权时间</span><strong>{{ formatDate(primaryBinding(apiType).authorized_at) }}</strong></div>
            <div><span>最近同步</span><strong>{{ formatDate(primaryBinding(apiType).last_run_at) }}</strong></div>
          </div>

          <el-form v-if="subjectType === 'warehouse' && apiType === 'inventory'" label-position="top" class="config-form warehouse-config-form">
            <el-form-item label="库存 API 接入配置">
              <el-select v-model="selections[apiType]" :disabled="!configsFor(apiType).length" placeholder="暂无可用库存 API 配置">
                <el-option
                  v-for="config in configsFor(apiType)"
                  :key="config.id"
                  :label="`${config.account_alias} · ${statusLabel(config.status)}`"
                  :value="config.id"
                />
              </el-select>
            </el-form-item>
            <el-alert
              v-if="selectedConfig(apiType) && !['configured', 'verified', 'active'].includes(selectedConfig(apiType).status)"
              title="当前配置未达到绑定条件，请先到连接配置完成维护和检查。"
              type="warning"
              :closable="false"
              show-icon
            />
          </el-form>

          <el-form v-else-if="!primaryBinding(apiType)" label-position="top" class="config-form">
            <el-form-item label="接入配置">
              <el-select v-model="selections[apiType]" :disabled="!configsFor(apiType).length" placeholder="暂无可用配置">
                <el-option
                  v-for="config in configsFor(apiType)"
                  :key="config.id"
                  :label="`${config.account_alias} · ${statusLabel(config.status)}`"
                  :value="config.id"
                />
              </el-select>
            </el-form-item>
            <el-alert
              v-if="selectedConfig(apiType) && !selectedConfig(apiType).oauth_ready"
              :title="oauthBlockerText(selectedConfig(apiType))"
              type="warning"
              :closable="false"
              show-icon
            />
          </el-form>

          <div class="section-actions">
            <el-button
              v-if="subjectType === 'warehouse' && apiType === 'inventory' && warehouseAuthorizeAccess.visible"
              :type="primaryBinding(apiType) ? 'default' : 'primary'"
              :loading="busy === `warehouse-bind-${apiType}`"
              :disabled="warehouseAuthorizeAccess.disabled || !selectedConfig(apiType)"
              :title="warehouseAuthorizeAccess.disabled ? warehouseAuthorizeAccess.reason : (primaryBinding(apiType) ? '受控更换当前仓库的库存 API 配置绑定' : '将当前已托管配置绑定到仓库')"
              @click="bindWarehouse(apiType)"
            >{{ primaryBinding(apiType) ? '更换绑定' : '绑定此配置' }}</el-button>
            <el-button
              v-if="subjectType === 'store' && canAuthorize(apiType) && storeAuthorizeAccess.visible"
              :type="primaryBinding(apiType) ? 'default' : 'primary'"
              :loading="busy === `authorize-${apiType}`"
              :disabled="storeAuthorizeAccess.disabled || !selectedConfig(apiType) || !selectedConfig(apiType).oauth_ready"
              :title="storeAuthorizeAccess.disabled ? storeAuthorizeAccess.reason : '发起平台 OAuth 授权'"
              @click="authorizeStore(apiType)"
            >
              {{ authorizeLabel(apiType) }}
            </el-button>
            <el-button
              v-if="subjectType === 'store' && primaryBinding(apiType) && !isMultipleAdvertising(apiType) && storeRefreshAccess.visible"
              :loading="busy === `refresh-${primaryBinding(apiType).id}`"
              :disabled="storeRefreshAccess.disabled"
              :title="storeRefreshAccess.reason"
              @click="refreshStoreBinding(primaryBinding(apiType))"
            >刷新令牌</el-button>
            <el-button
              v-if="primaryBinding(apiType)"
              @click="openAuthorizationDetail(primaryBinding(apiType))"
            >授权详情</el-button>
            <el-button
              v-if="subjectType === 'store' && primaryBinding(apiType) && storeSyncCreateAccess.visible"
              :disabled="storeSyncActionDisabled(apiType, primaryBinding(apiType))"
              :title="storeSyncActionTitle(apiType, primaryBinding(apiType))"
              @click="createStoreSyncJob(apiType, primaryBinding(apiType))"
            >创建同步任务</el-button>
            <el-select
              v-if="subjectType === 'store' && primaryBinding(apiType) && storeSyncResourceOptions(apiType).length > 1"
              v-model="storeSyncResourceSelection[primaryBinding(apiType).id]"
              class="store-sync-resource-select"
              aria-label="同步资源类型"
            >
              <el-option
                v-for="option in storeSyncResourceOptions(apiType)"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-button
              v-if="subjectType === 'warehouse' && apiType === 'inventory' && primaryBinding(apiType) && warehouseSyncCreateAccess.visible"
              :loading="busy === `warehouse-sync-${primaryBinding(apiType).id}`"
              :disabled="warehouseSyncCreateAccess.disabled"
              :title="warehouseSyncCreateAccess.disabled ? warehouseSyncCreateAccess.reason : '创建一个库存快照只读同步任务；重复点击不会创建重复任务'"
              @click="createInventorySyncJob(primaryBinding(apiType))"
            >创建库存同步任务</el-button>
            <el-button
              v-if="primaryBinding(apiType) && !isMultipleAdvertising(apiType) && supportsReadonlyCheck() && readonlyCheckAccess.visible"
              :loading="busy === `check-${primaryBinding(apiType).id}`"
              :disabled="readonlyCheckAccess.disabled || readonlyCheckBlocked(primaryBinding(apiType)) || !primaryBinding(apiType).integration_config_id"
              :title="readonlyCheckTitle(primaryBinding(apiType))"
              @click="checkToken(primaryBinding(apiType))"
            >{{ subjectType === 'warehouse' && apiType === 'inventory' ? '执行只读检查' : '平台只读检查' }}</el-button>
            <el-button
              v-if="subjectType === 'store' && primaryBinding(apiType) && !isMultipleAdvertising(apiType) && storeRevokeAccess.visible"
              :loading="busy === `disable-${primaryBinding(apiType).id}`"
              :disabled="storeRevokeAccess.disabled"
              :title="storeRevokeAccess.reason"
              @click="disableStoreBinding(primaryBinding(apiType))"
            >撤销授权</el-button>
            <el-button
              v-if="primaryBinding(apiType) && supportsReadonlyCheck() && syncViewAccess.visible"
              :disabled="syncViewAccess.disabled"
              :title="syncViewAccess.reason"
              @click="viewSyncJobs(apiType)"
            >查看同步任务</el-button>
            <el-button
              v-if="!configsFor(apiType).length && configViewAccess.visible"
              :disabled="configViewAccess.disabled"
              :title="configViewAccess.reason"
              @click="goToConfigs(apiType)"
            >配置 {{ apiLabels[apiType] }}</el-button>
            <el-button
              v-if="subjectType === 'warehouse' && apiType === 'inventory' && primaryBinding(apiType) && warehouseRevokeAccess.visible"
              type="danger"
              :loading="busy === `warehouse-revoke-${primaryBinding(apiType).id}`"
              :disabled="warehouseRevokeAccess.disabled"
              :title="warehouseRevokeAccess.disabled ? warehouseRevokeAccess.reason : '解除当前仓库的库存 API 绑定并停用关联同步任务'"
              @click="revokeWarehouseBinding(primaryBinding(apiType))"
            >解除绑定</el-button>
          </div>

          <div v-if="historyBindings(apiType).length" class="authorization-history">
            <div class="history-heading">
              <div>
                <h4>授权历史</h4>
                <p>保留待处理、已过期、已撤销和异常记录，便于定位失败原因；历史记录不可直接恢复。</p>
              </div>
              <el-tag type="info" effect="plain">{{ historyBindings(apiType).length }} 条</el-tag>
            </div>
            <el-table v-loading="historyLoading" :data="historyBindings(apiType)" border size="small" empty-text="暂无历史记录">
              <el-table-column label="状态" width="100">
                <template #default="{ row: historyRow }">
                  <el-tag :type="statusTagType(historyRow.status)" effect="plain">{{ statusLabel(historyRow.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="接入配置" min-width="150">
                <template #default="{ row: historyRow }">{{ historyRow.account_alias || configAlias(historyRow) || '—' }}</template>
              </el-table-column>
              <el-table-column label="授权范围" min-width="180">
                <template #default="{ row: historyRow }">{{ scopesLabel(historyRow) }}</template>
              </el-table-column>
              <el-table-column label="到期时间" min-width="170">
                <template #default="{ row: historyRow }">{{ formatDate(expirationDate(historyRow)) }}</template>
              </el-table-column>
              <el-table-column label="最近错误" min-width="220" show-overflow-tooltip>
                <template #default="{ row: historyRow }">{{ errorLabel(historyRow) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="{ row: historyRow }">
                  <el-button link type="primary" @click="openAuthorizationDetail(historyRow)">查看详情</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div v-if="subjectType === 'warehouse' && apiType === 'inventory'" class="reauthorize-panel">
            <div>
              <h4>{{ primaryBinding(apiType) ? '重新授权极风 WMS' : '授权极风 WMS' }}</h4>
              <p>一次性 Token 只通过受控凭据维护入口提交；本弹窗仅展示脱敏授权关系，不读取或回显凭据原文。</p>
            </div>
            <el-tag type="info" effect="light">受控维护</el-tag>
            <el-button
              v-if="selectedConfig(apiType) && credentialMaintenanceAccess.visible"
              type="primary"
              :disabled="credentialMaintenanceAccess.disabled"
              :title="credentialMaintenanceAccess.reason"
              @click="goToConfigs(apiType, { requiresCredentialRotate: true })"
            >维护接入凭据</el-button>
          </div>
        </section>
      </div>
    </template>

    <template #footer>
      <el-button :disabled="Boolean(busy)" @click="dialogVisible = false">关闭</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="authorizationDetailOpen"
    title="API 授权记录详情"
    width="min(680px, 94vw)"
    append-to-body
    destroy-on-close
  >
    <el-alert
      title="仅展示当前租户授权关系的脱敏元数据；凭据原文、Token 和密钥不会返回或回显。"
      type="info"
      :closable="false"
      show-icon
    />
    <el-descriptions v-if="selectedAuthorizationDetail" :column="1" border class="authorization-detail">
      <el-descriptions-item label="状态">
        <el-tag :type="statusTagType(selectedAuthorizationDetail.status)" effect="plain">
          {{ statusLabel(selectedAuthorizationDetail.status) }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="接入配置">{{ selectedAuthorizationDetail.account_alias || configAlias(selectedAuthorizationDetail) || '—' }}</el-descriptions-item>
      <el-descriptions-item label="平台主体 ID">{{ selectedAuthorizationDetail.platform_store_id || selectedAuthorizationDetail.warehouse_code || '—' }}</el-descriptions-item>
      <el-descriptions-item label="授权范围">{{ scopesLabel(selectedAuthorizationDetail) }}</el-descriptions-item>
      <el-descriptions-item label="授权时间">{{ formatDate(selectedAuthorizationDetail.authorized_at) }}</el-descriptions-item>
      <el-descriptions-item label="到期时间">{{ formatDate(expirationDate(selectedAuthorizationDetail)) }}</el-descriptions-item>
      <el-descriptions-item label="撤销时间">{{ formatDate(selectedAuthorizationDetail.revoked_at) }}</el-descriptions-item>
      <el-descriptions-item label="最近错误">{{ errorLabel(selectedAuthorizationDetail) }}</el-descriptions-item>
      <el-descriptions-item label="凭据掩码">{{ credentialMaskLabel(selectedAuthorizationDetail) }}</el-descriptions-item>
    </el-descriptions>
    <template #footer>
      <el-button @click="authorizationDetailOpen = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { getActionAccess } from '../utils/actionAccess';
import {
  bindWarehouseAuthorization,
  checkIntegrationReadonlyConnection,
  completeSyntheticStoreAuthorization,
  createSyncJob,
  fetchStoreAuthorizations,
  fetchSubjectApiAccess,
  fetchWarehouseAuthorizations,
  refreshStoreAuthorization,
  rebindWarehouseAuthorization,
  revokeWarehouseAuthorization,
  revokeStoreAuthorization,
  startStoreAuthorization,
} from '../api/integrations';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  subjectType: { type: String, required: true },
  row: { type: Object, default: null },
});
const emit = defineEmits(['update:modelValue', 'changed']);
const router = useRouter();
const auth = useAuthStore();
const loading = ref(false);
const busy = ref('');
const error = ref('');
const access = ref(null);
const selections = reactive({});
const storeSyncResourceSelection = reactive({});
const authorizationUrl = ref('');
const authorizationDetailOpen = ref(false);
const selectedAuthorizationDetail = ref(null);
const historyLoading = ref(false);
const historyError = ref('');

const apiLabels = { marketplace: '商城 API', advertising: '广告 API', inventory: '库存 API' };
const apiDescriptions = { marketplace: '销售订单与退款退货', advertising: '广告账户与广告报表', inventory: '极风 WMS 库存快照' };
// Keep this allow-list aligned with the backend platform capability registry.
// A marketplace API is not automatically an order API: only the registered
// Shopee/TikTok read-only resources can be selected here.  In particular,
// advertising and Lazada must not be mapped to an unsupported resource.
const storeSyncResourceRegistry = Object.freeze({
  shopee: Object.freeze(['sales_order', 'refund_return']),
  tiktok: Object.freeze(['sales_order', 'refund_return']),
  lazada: Object.freeze([]),
});
const storeSyncResourceLabels = {
  sales_order: '销售订单',
  refund_return: '退款退货',
};
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
});
const subjectViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.view', unauthorizedBehavior: 'disable' }));
const storeViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.store.view', unauthorizedBehavior: 'disable' }));
// auth.hasPermission accepts multiple codes as an OR check.  Store API access
// is intentionally stricter: both the generic integration-view permission and
// the store-scoped view permission are required before reading the dialog.
const storeApiViewAccess = computed(() => {
  const allowed = subjectViewAccess.value.allowed && storeViewAccess.value.allowed;
  return {
    allowed,
    visible: subjectViewAccess.value.visible && storeViewAccess.value.visible,
    disabled: !allowed,
    reason: subjectViewAccess.value.allowed
      ? storeViewAccess.value.reason
      : subjectViewAccess.value.reason,
  };
});
const storeAuthorizeAccess = computed(() => getActionAccess(auth, { permission: 'integrations.store.authorize', unauthorizedBehavior: 'disable' }));
const storeRevokeAccess = computed(() => getActionAccess(auth, { permission: 'integrations.store.revoke', unauthorizedBehavior: 'disable' }));
const readonlyCheckAccess = computed(() => getActionAccess(auth, { permission: 'integrations.run_live_readonly', unauthorizedBehavior: 'disable' }));
const configViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.config.view', unauthorizedBehavior: 'disable' }));
const credentialRotateAccess = computed(() => getActionAccess(auth, { permission: 'integrations.credential.rotate', unauthorizedBehavior: 'disable' }));
const storeRefreshAccess = computed(() => {
  const allowed = storeAuthorizeAccess.value.allowed && credentialRotateAccess.value.allowed;
  return {
    allowed,
    visible: storeAuthorizeAccess.value.visible && credentialRotateAccess.value.visible,
    disabled: !allowed,
    reason: storeAuthorizeAccess.value.allowed
      ? credentialRotateAccess.value.reason
      : storeAuthorizeAccess.value.reason,
  };
});
const warehouseViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.warehouse.view', unauthorizedBehavior: 'disable' }));
const warehouseAuthorizeAccess = computed(() => getActionAccess(auth, { permission: 'integrations.warehouse.authorize', unauthorizedBehavior: 'disable' }));
const warehouseRevokeAccess = computed(() => getActionAccess(auth, { permission: 'integrations.warehouse.revoke', unauthorizedBehavior: 'disable' }));
const warehouseSyncCreateAccess = computed(() => getActionAccess(auth, { permission: 'integrations.manage', unauthorizedBehavior: 'disable' }));
const storeSyncCreateAccess = computed(() => getActionAccess(auth, { permission: 'integrations.manage', unauthorizedBehavior: 'disable' }));
const syncViewAccess = subjectViewAccess;
const credentialMaintenanceAccess = computed(() => {
  const allowed = configViewAccess.value.allowed && credentialRotateAccess.value.allowed;
  return {
    allowed,
    visible: configViewAccess.value.visible && credentialRotateAccess.value.visible,
    disabled: !allowed,
    reason: configViewAccess.value.allowed
      ? credentialRotateAccess.value.reason
      : configViewAccess.value.reason,
  };
});
const subtitle = computed(() => props.subjectType === 'store'
  ? '从当前店铺发起授权，回调后直接加密写入并绑定 SaaS MySQL'
  : '从当前仓库维护授权关系，凭据只通过受控入口加密写入 SaaS MySQL');
const tokenPolicyLabel = computed(() => ({
  'tiktok-split-policy': '商城不自动刷新；广告独立长期 Token',
  'oauth-auto-refresh': 'OAuth Token 到期前自动刷新',
  'auto-refresh': '到期前自动刷新；检查时调用只读 API',
  'manual-no-expiry-block': '不自动刷新，不设到期拦截',
  'manual-replace': '仅手动绑定或替换',
}[access.value?.token_policy] || '遵循平台默认令牌策略'));

function statusLabel(value) {
  return ({
    authorized: '已授权',
    active: '已启用',
    configured: '已配置',
    verified: '已检查',
    disabled: '已禁用',
    pending: '待处理',
    expired: '已过期',
    revoked: '已撤销',
    error: '异常',
  }[value] || value || '未绑定');
}

function statusTagType(value) {
  return ({
    authorized: 'success',
    active: 'success',
    configured: 'info',
    verified: 'success',
    disabled: 'info',
    pending: 'warning',
    expired: 'warning',
    revoked: 'info',
    error: 'danger',
  }[value] || 'info');
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false });
}

function configsFor(apiType) {
  return (access.value?.configs || []).filter((config) => config.api_type === apiType);
}

function activeBindings(apiType) {
  return (access.value?.bindings || []).filter((binding) => binding.api_type === apiType && ['authorized', 'active'].includes(binding.status));
}

function allBindings(apiType) {
  return (access.value?.bindings || []).filter((binding) => binding.api_type === apiType);
}

function historyBindings(apiType) {
  return allBindings(apiType).filter((binding) => !['authorized', 'active'].includes(binding.status));
}

function primaryBinding(apiType) {
  return activeBindings(apiType)[0] || null;
}

function isMultipleAdvertising(apiType) {
  return apiType === 'advertising' && access.value?.subject?.platform === 'tiktok' && activeBindings(apiType).length > 0;
}

function bindingStatus(apiType) {
  const bindings = activeBindings(apiType);
  if (!bindings.length) return '未绑定';
  if (isMultipleAdvertising(apiType)) return `已绑定 ${bindings.length} 个`;
  return statusLabel(bindings[0].status);
}

function selectedConfig(apiType) {
  const binding = primaryBinding(apiType);
  return configsFor(apiType).find((config) => config.id === (selections[apiType] || binding?.integration_config_id)) || null;
}

function configAlias(binding) {
  return configsFor(binding?.api_type).find(
    (config) => String(config.id) === String(binding?.integration_config_id),
  )?.account_alias || '';
}

function scopesLabel(binding) {
  const scopes = Array.isArray(binding?.scopes) && binding.scopes.length
    ? binding.scopes
    : configsFor(binding?.api_type).find(
      (config) => String(config.id) === String(binding?.integration_config_id),
    )?.scopes;
  return Array.isArray(scopes) && scopes.length ? scopes.join('、') : '未返回已声明范围';
}

function expirationDate(binding) {
  return binding?.expires_at || binding?.token_expires_at || null;
}

function errorLabel(binding) {
  const code = binding?.last_error_code || '';
  const message = binding?.masked_error_message || binding?.last_error_message || '';
  return [code, message].filter(Boolean).join('：') || '无脱敏错误';
}

function credentialMaskLabel(binding) {
  const mask = binding?.credential_mask;
  if (!mask || typeof mask !== 'object' || Array.isArray(mask) || !Object.keys(mask).length) {
    return binding?.credential_status === 'referenced' ? '已托管引用（未返回掩码）' : '未返回凭据掩码';
  }
  return Object.entries(mask)
    .map(([key, value]) => key + '=' + String(value || '—'))
    .join('；');
}

function openAuthorizationDetail(binding) {
  selectedAuthorizationDetail.value = binding ? { ...binding } : null;
  authorizationDetailOpen.value = Boolean(binding);
}

function responseRows(response) {
  return response?.data?.results
    || response?.data?.items
    || (Array.isArray(response?.data) ? response.data : []);
}

async function loadAuthorizationHistory(subjectType, subjectId, baseAccess) {
  historyLoading.value = true;
  historyError.value = '';
  try {
    const response = subjectType === 'warehouse'
      ? await fetchWarehouseAuthorizations({ warehouse_id: subjectId, page: 1, page_size: 100 })
      : await fetchStoreAuthorizations({ store_id: subjectId, page: 1, page_size: 100 });
    if (!response?.success) throw new Error(response?.message || '授权历史读取失败');
    const configMap = new Map((baseAccess.configs || []).map((config) => [String(config.id), config]));
    const merged = [...(baseAccess.bindings || [])];
    for (const row of responseRows(response)) {
      const apiType = row.api_type
        || (subjectType === 'warehouse' ? 'inventory' : configMap.get(String(row.integration_config_id))?.api_type || 'marketplace');
      const normalized = {
        ...row,
        api_type: apiType,
        account_alias: row.account_alias || configMap.get(String(row.integration_config_id))?.account_alias || '',
      };
      const existingIndex = merged.findIndex((item) => String(item.id) === String(row.id));
      if (existingIndex >= 0) merged[existingIndex] = { ...merged[existingIndex], ...normalized };
      else merged.push(normalized);
    }
    access.value = { ...baseAccess, bindings: merged };
  } catch (reason) {
    historyError.value = reason?.message || '授权历史读取失败；当前仅展示主体 API 摘要。';
  } finally {
    historyLoading.value = false;
  }
}

const oauthBlockerLabels = {
  config_missing: '未找到接入配置',
  platform_mismatch: '平台与接入配置不一致',
  environment_not_live: '配置不是受控试运行或生产环境',
  platform_network_mode_disabled: '正式平台网络模式尚未启用',
  platform_security_not_approved: '正式平台安全审批尚未启用',
  credential_custody_not_approved: '独立凭据保管服务尚未就绪',
  outbound_host_allowlist_missing: '平台出口域名白名单尚未配置',
  platform_contract_not_enabled: '平台合同开关尚未批准',
  network_not_approved: '平台网络访问尚未批准',
  write_sync_enabled: '生产写同步必须关闭',
  config_not_approved: '接入配置尚未完成审核',
  credential_not_configured: '开发者凭据尚未配置',
  credential_reference_missing: '开发者凭据引用缺失',
  contract_not_approved: '平台合同版本尚未批准',
  callback_missing: 'Shopee 授权回调地址尚未配置',
  callback_allowlist_missing: '生产回调白名单尚未配置',
  callback_mismatch: '授权回调地址与平台登记值不一致',
  callback_not_allowlisted: '授权回调地址不在生产白名单',
  public_app_id_missing: '平台应用标识尚未配置',
};

function oauthBlockerText(config) {
  const reasons = (config?.oauth_blockers || []).map((code) => oauthBlockerLabels[code] || code);
  return reasons.length ? `暂不可授权：${reasons.join('；')}。请先到“连接配置”完成整改。` : '';
}

function canAuthorize(apiType) {
  const platform = access.value?.subject?.platform;
  return ['lazada', 'shopee', 'tiktok'].includes(platform)
    && (apiType === 'marketplace' || (apiType === 'advertising' && platform !== 'lazada'));
}

function authorizeLabel(apiType) {
  const platform = ({ lazada: 'Lazada', shopee: 'Shopee', tiktok: 'TikTok' })[access.value?.subject?.platform] || '平台';
  if (isMultipleAdvertising(apiType)) return `继续绑定 ${platform} 广告户`;
  return `${primaryBinding(apiType) ? '重新授权' : '授权'} ${platform}${apiType === 'advertising' ? ' 广告账户' : ' 店铺'}`;
}

function supportsReadonlyCheck() {
  return access.value?.subject?.platform !== 'lazada';
}

async function load() {
  if (!props.row?.id) return;
  if (props.subjectType === 'store') {
    if (!storeApiViewAccess.value.allowed) {
      error.value = storeApiViewAccess.value.reason || '当前角色无权查看店铺 API 接入信息';
      return;
    }
  } else {
    if (!subjectViewAccess.value.allowed) {
      error.value = subjectViewAccess.value.reason || '当前角色无权查看 API 接入信息';
      return;
    }
  }
  if (props.subjectType === 'warehouse' && !warehouseViewAccess.value.allowed) {
    error.value = warehouseViewAccess.value.reason || '当前角色无权查看仓库 API 授权';
    return;
  }
  loading.value = true;
  error.value = '';
  historyError.value = '';
  authorizationUrl.value = '';
  access.value = null;
  try {
    const response = await fetchSubjectApiAccess(props.subjectType, props.row.id);
    if (!response?.success) throw new Error(response?.message || 'API 接入信息读取失败');
    access.value = response.data;
    await loadAuthorizationHistory(props.subjectType, props.row.id, response.data);
    for (const apiType of response.data?.api_types || []) {
      const binding = primaryBinding(apiType);
      selections[apiType] = binding?.integration_config_id || configsFor(apiType)[0]?.id || '';
      const resourceOptions = storeSyncResourceOptions(apiType);
      if (binding && resourceOptions.length && !storeSyncResourceSelection[binding.id]) {
        storeSyncResourceSelection[binding.id] = resourceOptions[0].value;
      }
    }
  } catch (reason) {
    error.value = reason?.message || 'API 接入信息读取失败';
  } finally {
    loading.value = false;
  }
}

async function authorizeStore(apiType) {
  if (props.subjectType !== 'store' || !storeAuthorizeAccess.value.allowed) {
    ElMessage.warning(storeAuthorizeAccess.value.reason || '当前角色无权发起店铺授权');
    return;
  }
  const config = selectedConfig(apiType);
  if (!config) {
    ElMessage.warning('请先选择可用的接入配置');
    return;
  }
  if (!config.oauth_ready) {
    ElMessage.warning(oauthBlockerText(config) || '当前接入配置尚未达到授权条件。');
    return;
  }
  busy.value = `authorize-${apiType}`;
  try {
    const response = await startStoreAuthorization({
      platform: access.value.subject.platform,
      integration_config_id: config.id,
      store_id: access.value.subject.id,
      region: access.value.subject.country_code,
      redirect_uri: config.callback_url,
      scopes: config.scopes || [],
    });
    if (!response?.success) throw new Error(response?.message || '授权发起失败');
    if (response.data?.simulation_callback) {
      const callback = await completeSyntheticStoreAuthorization(
        access.value.subject.platform,
        response.data.simulation_callback,
      );
      if (!callback?.success) throw new Error(callback?.message || '本地模拟授权回调失败');
      ElMessage.success('本地模拟授权已完成。');
      await load();
      emit('changed');
      return;
    }
    const rawAuthorizationUrl = String(response.data?.authorization_url || '').trim();
    if (!rawAuthorizationUrl) throw new Error('授权地址为空');
    const target = new URL(rawAuthorizationUrl, window.location.origin);
    if (!['http:', 'https:'].includes(target.protocol)) throw new Error('授权地址无效');
    let popup = null;
    try {
      popup = window.open(target.toString(), '_blank', 'noopener,noreferrer');
    } catch (_popupError) {
      popup = null;
    }
    if (popup) {
      authorizationUrl.value = '';
      ElMessage.info('已打开平台授权页，授权完成后请返回并重新打开本弹窗。');
    } else {
      authorizationUrl.value = target.toString();
      let copied = false;
      try {
        const writeText = globalThis.navigator?.clipboard?.writeText;
        if (typeof writeText !== 'function') throw new Error('Clipboard API unavailable');
        await writeText.call(globalThis.navigator.clipboard, authorizationUrl.value);
        copied = true;
      } catch (_copyError) {
        copied = false;
      }
      ElMessage.warning(copied
        ? '浏览器阻止了新窗口，授权地址已复制，请粘贴到新标签页继续。'
        : '浏览器阻止了新窗口，请允许弹窗后重试；授权地址未能自动复制。');
    }
  } catch (reason) {
    ElMessage.error(reason?.message || '授权发起失败');
  } finally {
    busy.value = '';
  }
}

async function checkToken(binding) {
  if (!readonlyCheckAccess.value.allowed) {
    ElMessage.warning(readonlyCheckAccess.value.reason || '当前角色无权执行平台只读检查');
    return;
  }
  if (!binding?.integration_config_id) {
    ElMessage.warning('当前授权缺少接入配置，无法执行平台只读检查');
    return;
  }
  if (readonlyCheckBlocked(binding)) {
    ElMessage.warning('请先创建库存同步任务，再执行只读检查。');
    return;
  }
  try {
    await ElMessageBox.confirm(
      '将调用一次平台只读接口，仅验证当前授权连接；不会刷新或替换 Token。是否继续？',
      '确认平台只读检查',
      { type: 'warning', confirmButtonText: '确认检查', cancelButtonText: '取消' },
    );
  } catch (_reason) {
    return;
  }
  busy.value = `check-${binding.id}`;
  try {
    const response = await checkIntegrationReadonlyConnection(
      binding.integration_config_id,
      props.subjectType === 'warehouse'
        ? { warehouse_authorization_id: binding.id }
        : { store_authorization_id: binding.id },
    );
    if (!response?.success) throw new Error(response?.message || '平台只读检查失败');
    if (response.data?.simulated === true && response.data?.external_api_called === false) {
      ElMessage.info('模拟检查完成，未调用真实平台。');
    } else {
      ElMessage.success('只读 API 检查通过，授权凭据可用于当前同步任务。');
    }
    await load();
  } catch (reason) {
    ElMessage.error(reason?.message || '平台只读检查失败');
  } finally {
    busy.value = '';
  }
}

async function refreshStoreBinding(binding) {
  if (props.subjectType !== 'store' || !storeRefreshAccess.value.allowed) {
    ElMessage.warning(storeRefreshAccess.value.reason || '当前角色无权刷新令牌');
    return;
  }
  if (!binding?.id) {
    ElMessage.warning('当前授权记录无效，无法刷新令牌');
    return;
  }
  try {
    await ElMessageBox.confirm(
      '将向平台刷新当前店铺授权令牌，操作结果会写入集成审计。是否继续？',
      '确认刷新令牌',
      { type: 'warning', confirmButtonText: '确认刷新', cancelButtonText: '取消' },
    );
  } catch (_reason) {
    return;
  }
  busy.value = `refresh-${binding.id}`;
  try {
    const response = await refreshStoreAuthorization(binding.id, { confirmed: true });
    if (!response?.success) throw new Error(response?.message || '令牌刷新失败');
    ElMessage.success('令牌已刷新');
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '令牌刷新失败');
  } finally {
    busy.value = '';
  }
}

async function disableStoreBinding(binding) {
  if (props.subjectType !== 'store' || !storeRevokeAccess.value.allowed) {
    ElMessage.warning(storeRevokeAccess.value.reason || '当前角色无权撤销店铺授权');
    return;
  }
  if (!binding?.id) {
    ElMessage.warning('当前授权记录无效，无法撤销');
    return;
  }
  try {
    await ElMessageBox.confirm('撤销后关联授权将不可继续使用，确认撤销？', '撤销授权', { type: 'warning', confirmButtonText: '确认撤销', cancelButtonText: '取消' });
  } catch (_reason) {
    return;
  }
  busy.value = `disable-${binding.id}`;
  try {
    const response = await revokeStoreAuthorization(binding.id);
    if (!response?.success) throw new Error(response?.message || '撤销授权失败');
    ElMessage.success('授权已撤销');
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '撤销授权失败');
  } finally {
    busy.value = '';
  }
}

async function copyAuthorizationUrl() {
  if (!authorizationUrl.value) return;
  try {
    const writeText = globalThis.navigator?.clipboard?.writeText;
    if (typeof writeText !== 'function') throw new Error('Clipboard API unavailable');
    await writeText.call(globalThis.navigator.clipboard, authorizationUrl.value);
    ElMessage.success('授权地址已复制');
  } catch (_copyError) {
    ElMessage.warning('复制失败，请手动选择并复制授权地址。');
  }
}

function storeSyncResourceOptions(apiType) {
  if (apiType !== 'marketplace') return [];
  const platform = String(access.value?.subject?.platform || '').toLowerCase();
  return (storeSyncResourceRegistry[platform] || []).map((value) => ({
    value,
    label: storeSyncResourceLabels[value] || value,
  }));
}

function storeSyncResourceType(apiType, binding) {
  const options = storeSyncResourceOptions(apiType);
  const selected = storeSyncResourceSelection[binding?.id];
  return options.some((option) => option.value === selected)
    ? selected
    : options[0]?.value || '';
}

function storeSyncActionDisabled(apiType, binding) {
  return storeSyncCreateAccess.value.disabled
    || !storeSyncResourceOptions(apiType).length
    || !storeSyncResourceType(apiType, binding);
}

function storeSyncActionTitle(apiType, binding) {
  if (storeSyncCreateAccess.value.disabled) return storeSyncCreateAccess.value.reason;
  if (!storeSyncResourceOptions(apiType).length) {
    return apiType === 'advertising'
      ? '广告 API 尚未注册可创建的只读同步资源，暂不可创建同步任务'
      : '当前平台没有已注册的只读同步资源，暂不可创建同步任务';
  }
  const resourceType = storeSyncResourceType(apiType, binding);
  return `为当前店铺授权创建${storeSyncResourceLabels[resourceType] || resourceType}只读同步任务`;
}

async function createStoreSyncJob(apiType, binding) {
  if (props.subjectType !== 'store' || !storeSyncCreateAccess.value.allowed) {
    ElMessage.warning(storeSyncCreateAccess.value.reason || '当前角色无权创建店铺同步任务');
    return;
  }
  if (!binding?.id || !binding.integration_config_id) {
    ElMessage.warning('请先选择有效的店铺授权和接入配置');
    return;
  }
  const resourceType = storeSyncResourceType(apiType, binding);
  if (!resourceType) {
    ElMessage.info(storeSyncActionTitle(apiType, binding));
    return;
  }
  try {
    await ElMessageBox.confirm(
      '将为当前店铺授权创建 ' + (storeSyncResourceLabels[resourceType] || resourceType) + ' 只读同步任务，不会写入平台业务数据。是否继续？',
      '确认创建同步任务',
      { type: 'info', confirmButtonText: '确认创建', cancelButtonText: '取消' },
    );
  } catch (_reason) {
    return;
  }
  busy.value = 'store-sync-' + binding.id;
  try {
    const response = await createSyncJob({
      integration_config_id: binding.integration_config_id,
      store_authorization_id: binding.id,
      resource_type: resourceType,
      schedule_type: 'manual',
      is_enabled: true,
      max_retry_count: 3,
      backoff_base_seconds: 2,
    });
    if (!response?.success) {
      const duplicate = response?.code === 'DUPLICATE_SYNC_JOB'
        || /已经存在|已存在|already has/i.test(String(response?.message || ''));
      if (!duplicate) throw new Error(response?.message || '店铺同步任务创建失败');
      ElMessage.info('该店铺授权已有对应同步任务，无需重复创建。');
      return;
    }
    ElMessage.success(response.data?.idempotent ? '该店铺授权已有同步任务，无需重复创建。' : '店铺同步任务已创建。');
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '店铺同步任务创建失败');
  } finally {
    busy.value = '';
  }
}

async function bindWarehouse(apiType) {
  if (props.subjectType !== 'warehouse' || apiType !== 'inventory') return;
  if (!warehouseAuthorizeAccess.value.allowed) {
    ElMessage.warning(warehouseAuthorizeAccess.value.reason || '当前角色无权绑定仓库 API');
    return;
  }
  const config = selectedConfig(apiType);
  if (!config) {
    ElMessage.warning('请先选择库存 API 接入配置');
    return;
  }
  const binding = primaryBinding(apiType);
  if (binding && String(binding.integration_config_id) === String(config.id)) {
    ElMessage.info('当前仓库已经绑定此配置，无需重复操作。');
    return;
  }
  if (binding) {
    try {
      await ElMessageBox.confirm(
        `将把当前仓库的库存 API 绑定从“${binding.account_alias || '当前配置'}”更换为“${config.account_alias || '所选配置'}”，关联同步任务会先停用。是否继续？`,
        '确认更换绑定',
        { type: 'warning', confirmButtonText: '确认更换', cancelButtonText: '取消' },
      );
    } catch (_reason) {
      return;
    }
  }
  busy.value = `warehouse-bind-${apiType}`;
  try {
    const payload = {
      warehouse_id: access.value.subject.id,
      integration_config_id: config.id,
      replace: Boolean(binding),
      ...(binding ? { expected_authorization_id: binding.id } : {})
    };
    const response = binding
      ? await rebindWarehouseAuthorization(binding.id, payload)
      : await bindWarehouseAuthorization(payload);
    if (!response?.success) throw new Error(response?.message || '仓库 API 绑定失败');
    ElMessage.success(response.data?.idempotent ? '绑定关系已存在，无需重复操作。' : (binding ? '仓库 API 绑定已更换。' : '仓库 API 已绑定。'));
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '仓库 API 绑定失败');
  } finally {
    busy.value = '';
  }
}

async function revokeWarehouseBinding(binding) {
  if (props.subjectType !== 'warehouse' || !warehouseRevokeAccess.value.allowed) {
    ElMessage.warning(warehouseRevokeAccess.value.reason || '当前角色无权解除仓库 API 绑定');
    return;
  }
  if (!binding?.id) {
    ElMessage.warning('当前仓库 API 绑定记录无效');
    return;
  }
  try {
    await ElMessageBox.confirm(
      '解除绑定后，关联库存同步任务会被停用；接入配置和托管凭据不会删除。确认继续？',
      '确认解除绑定',
      { type: 'warning', confirmButtonText: '确认解除', cancelButtonText: '取消' },
    );
  } catch (_reason) {
    return;
  }
  busy.value = `warehouse-revoke-${binding.id}`;
  try {
    const response = await revokeWarehouseAuthorization(binding.id);
    if (!response?.success) throw new Error(response?.message || '解除仓库 API 绑定失败');
    ElMessage.success(response.data?.idempotent ? '仓库 API 绑定已经解除。' : '仓库 API 绑定已解除。');
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '解除仓库 API 绑定失败');
  } finally {
    busy.value = '';
  }
}

async function createInventorySyncJob(binding) {
  if (props.subjectType !== 'warehouse' || !warehouseSyncCreateAccess.value.allowed) {
    ElMessage.warning(warehouseSyncCreateAccess.value.reason || '当前角色无权创建库存同步任务');
    return;
  }
  if (!binding?.id || !binding.integration_config_id) {
    ElMessage.warning('请先绑定有效的仓库库存 API 配置');
    return;
  }
  busy.value = `warehouse-sync-${binding.id}`;
  try {
    const response = await createSyncJob({
      integration_config_id: binding.integration_config_id,
      warehouse_authorization_id: binding.id,
      resource_type: 'inventory_snapshot',
      schedule_type: 'manual',
      is_enabled: true,
      max_retry_count: 3,
      backoff_base_seconds: 1
    });
    if (!response?.success) {
      const duplicate = response?.code === 'DUPLICATE_SYNC_JOB'
        || /已经存在|已存在/.test(String(response?.message || ''));
      if (!duplicate) throw new Error(response?.message || '库存同步任务创建失败');
      ElMessage.info('该仓库已存在库存同步任务，无需重复创建。');
      await load();
      emit('changed');
      return;
    }
    ElMessage.success(response.data?.idempotent ? '库存同步任务已存在，无需重复创建。' : '库存同步任务已创建，可在同步任务中查看。');
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '库存同步任务创建失败');
  } finally {
    busy.value = '';
  }
}

function viewSyncJobs(apiType) {
  if (!syncViewAccess.value.allowed) {
    ElMessage.warning(syncViewAccess.value.reason || '当前角色无权查看同步任务');
    return;
  }
  if (!access.value?.subject?.platform) return;
  dialogVisible.value = false;
  router.push({ path: '/integrations/sync-jobs', query: {
    platform: access.value.subject.platform,
    api_type: apiType,
    subject: access.value.subject.name,
  } });
}

function readonlyCheckBlocked(binding) {
  return props.subjectType === 'warehouse' && binding?.has_sync_job === false;
}

function readonlyCheckTitle(binding) {
  if (readonlyCheckBlocked(binding)) return '请先创建库存同步任务，再执行只读检查。';
  if (readonlyCheckAccess.value.disabled) return readonlyCheckAccess.value.reason;
  if (!binding?.integration_config_id) return '当前授权缺少接入配置，无法执行平台只读检查';
  return '调用一次平台只读接口，不会刷新或替换 Token';
}

function goToConfigs(apiType, options = {}) {
  const actionAccess = options.requiresCredentialRotate ? credentialMaintenanceAccess.value : configViewAccess.value;
  if (!actionAccess.allowed) {
    ElMessage.warning(actionAccess.reason || '当前角色无权进入接入配置');
    return;
  }
  if (!access.value?.subject?.platform) return;
  const selected = options.requiresCredentialRotate ? selectedConfig(apiType) : null;
  const query = {
    platform: access.value.subject.platform,
    api_type: apiType,
  };
  if (selected?.id) {
    query.action = 'credentials';
    query.config_id = selected.id;
  }
  dialogVisible.value = false;
  router.push({ path: '/integrations/configs', query });
}
</script>

<style scoped>
.dialog-title h2 { margin: 0; color: #1f2937; font-size: 20px; line-height: 1.35; }
.dialog-title p { margin: 3px 0 0; color: #6b7280; font-size: 13px; }
.subject-summary { display: grid; grid-template-columns: 1fr 1fr 1.4fr; margin: 2px 0 16px; border: 1px solid #d9e2ef; border-radius: 10px; overflow: hidden; background: #f8fafc; }
.subject-summary > div { min-width: 0; padding: 14px 16px; border-right: 1px solid #d9e2ef; }
.subject-summary > div:last-child { border-right: 0; }
.subject-summary span, .binding-grid span, .advertiser-heading span { display: block; margin-bottom: 5px; color: #64748b; font-size: 12px; }
.subject-summary strong, .binding-grid strong, .advertiser-heading strong { color: #27364a; font-size: 14px; overflow-wrap: anywhere; }
.access-list { display: grid; gap: 14px; }
.access-section { padding: 16px; border: 1px solid #d9e2ef; border-radius: 10px; }
.section-heading, .advertiser-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.section-heading h3, .reauthorize-panel h4 { margin: 0; color: #263241; font-size: 18px; }
.section-heading p, .reauthorize-panel p { margin: 4px 0 0; color: #7a8492; font-size: 13px; line-height: 1.6; }
.binding-grid { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 14px; border: 1px solid #e1e7ef; border-radius: 8px; overflow: hidden; }
.binding-grid.is-primary { grid-template-columns: repeat(4, 1fr); }
.binding-grid > div { min-width: 0; padding: 12px 14px; border-right: 1px solid #e1e7ef; }
.binding-grid > div:last-child { border-right: 0; }
.config-form { max-width: 430px; margin-top: 14px; }
.config-form :deep(.el-form-item) { margin-bottom: 0; }
.config-form :deep(.el-select) { width: 100%; }
.section-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.advertiser-list { display: grid; gap: 12px; margin-top: 14px; }
.advertiser-binding { padding: 12px 14px; border: 1px solid #e1e7ef; border-radius: 8px; background: #fbfcfe; }
.advertiser-binding .binding-grid { border-right: 0; border-left: 0; border-radius: 0; }
.authorization-history { margin-top: 16px; padding-top: 16px; border-top: 1px solid #e1e7ef; }
.history-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 10px; }
.history-heading h4 { margin: 0; color: #334155; font-size: 15px; }
.history-heading p { margin: 4px 0 0; color: #7a8492; font-size: 12px; line-height: 1.5; }
.authorization-detail { margin-top: 14px; }
.reauthorize-panel { display: grid; grid-template-columns: 1fr auto; gap: 12px 16px; align-items: start; margin-top: 16px; padding-top: 16px; border-top: 1px solid #e1e7ef; }
.reauthorize-panel .el-button { grid-column: 1 / -1; justify-self: start; }
@media (max-width: 760px) {
  .subject-summary, .binding-grid, .binding-grid.is-primary { grid-template-columns: 1fr; }
  .subject-summary > div, .binding-grid > div { border-right: 0; border-bottom: 1px solid #d9e2ef; }
  .subject-summary > div:last-child, .binding-grid > div:last-child { border-bottom: 0; }
}
</style>
