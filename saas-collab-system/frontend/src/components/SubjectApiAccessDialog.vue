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
                <el-button :loading="busy === `check-${binding.id}`" @click="checkToken(binding)">检查 Token</el-button>
                <el-button :loading="busy === `disable-${binding.id}`" @click="disableStoreBinding(binding)">禁用此广告户</el-button>
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

          <el-form v-else label-position="top" class="config-form">
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
              v-if="subjectType === 'store' && canAuthorize(apiType)"
              :type="primaryBinding(apiType) ? 'default' : 'primary'"
              :loading="busy === `authorize-${apiType}`"
              :disabled="!selectedConfig(apiType) || !selectedConfig(apiType).oauth_ready"
              @click="authorizeStore(apiType)"
            >
              {{ authorizeLabel(apiType) }}
            </el-button>
            <el-button
              v-if="primaryBinding(apiType) && !isMultipleAdvertising(apiType) && supportsReadonlyCheck()"
              :loading="busy === `check-${primaryBinding(apiType).id}`"
              @click="checkToken(primaryBinding(apiType))"
            >检查 Token</el-button>
            <el-button
              v-if="subjectType === 'store' && primaryBinding(apiType) && !isMultipleAdvertising(apiType)"
              :loading="busy === `disable-${primaryBinding(apiType).id}`"
              @click="disableStoreBinding(primaryBinding(apiType))"
            >禁用授权</el-button>
            <el-button v-if="primaryBinding(apiType) && supportsReadonlyCheck()" @click="viewSyncJobs(apiType)">查看同步任务</el-button>
            <el-button v-if="!configsFor(apiType).length" @click="goToConfigs(apiType)">配置 {{ apiLabels[apiType] }}</el-button>
          </div>

          <div v-if="subjectType === 'warehouse' && apiType === 'inventory'" class="reauthorize-panel">
            <div>
              <h4>{{ primaryBinding(apiType) ? '重新授权极风 WMS' : '授权极风 WMS' }}</h4>
              <p>一次性 Token 只通过受控凭据维护入口提交；本弹窗仅展示脱敏授权关系，不读取或回显凭据原文。</p>
            </div>
            <el-tag type="info" effect="light">受控维护</el-tag>
            <el-button type="primary" @click="goToConfigs(apiType)">维护接入凭据</el-button>
          </div>
        </section>
      </div>
    </template>

    <template #footer>
      <el-button :disabled="Boolean(busy)" @click="dialogVisible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRouter } from 'vue-router';
import {
  checkIntegrationReadonlyConnection,
  completeSyntheticStoreAuthorization,
  fetchSubjectApiAccess,
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
const loading = ref(false);
const busy = ref('');
const error = ref('');
const access = ref(null);
const selections = reactive({});

const apiLabels = { marketplace: '商城 API', advertising: '广告 API', inventory: '库存 API' };
const apiDescriptions = { marketplace: '销售订单与退款退货', advertising: '广告账户与广告报表', inventory: '极风 WMS 库存快照' };
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
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
  return ({ authorized: '已授权', active: '已启用', configured: '已配置', verified: '已检查', disabled: '已禁用', error: '异常', pending: '待处理' }[value] || value || '未绑定');
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
  return configsFor(apiType).find((config) => config.id === (binding?.integration_config_id || selections[apiType])) || null;
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
  loading.value = true;
  error.value = '';
  access.value = null;
  try {
    const response = await fetchSubjectApiAccess(props.subjectType, props.row.id);
    if (!response?.success) throw new Error(response?.message || 'API 接入信息读取失败');
    access.value = response.data;
    for (const apiType of response.data?.api_types || []) {
      selections[apiType] = primaryBinding(apiType)?.integration_config_id || configsFor(apiType)[0]?.id || '';
    }
  } catch (reason) {
    error.value = reason?.message || 'API 接入信息读取失败';
  } finally {
    loading.value = false;
  }
}

async function authorizeStore(apiType) {
  const config = selectedConfig(apiType);
  if (!config) return;
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
    const target = new URL(response.data?.authorization_url || '', window.location.origin);
    if (!['http:', 'https:'].includes(target.protocol)) throw new Error('授权地址无效');
    window.open(target.toString(), '_blank', 'noopener,noreferrer');
    ElMessage.info('已打开平台授权页，授权完成后请返回并重新打开本弹窗。');
  } catch (reason) {
    ElMessage.error(reason?.message || '授权发起失败');
  } finally {
    busy.value = '';
  }
}

async function checkToken(binding) {
  busy.value = `check-${binding.id}`;
  try {
    const response = await checkIntegrationReadonlyConnection(binding.integration_config_id);
    if (!response?.success) throw new Error(response?.message || 'Token 检查失败');
    ElMessage.success('只读 API 检查通过，授权凭据可用于当前同步任务。');
    await load();
  } catch (reason) {
    ElMessage.error(reason?.message || 'Token 检查失败');
  } finally {
    busy.value = '';
  }
}

async function disableStoreBinding(binding) {
  try {
    await ElMessageBox.confirm('禁用后关联授权将不可继续使用，确认禁用？', '禁用授权', { type: 'warning' });
  } catch (_reason) {
    return;
  }
  busy.value = `disable-${binding.id}`;
  try {
    const response = await revokeStoreAuthorization(binding.id);
    if (!response?.success) throw new Error(response?.message || '禁用授权失败');
    ElMessage.success('授权已禁用');
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '禁用授权失败');
  } finally {
    busy.value = '';
  }
}

function viewSyncJobs(apiType) {
  dialogVisible.value = false;
  router.push({ path: '/integrations/sync-jobs', query: {
    platform: access.value.subject.platform,
    api_type: apiType,
    search: access.value.subject.name,
  } });
}

function goToConfigs(apiType) {
  dialogVisible.value = false;
  router.push({ path: '/integrations/configs', query: {
    platform: access.value.subject.platform,
    api_type: apiType,
  } });
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
.reauthorize-panel { display: grid; grid-template-columns: 1fr auto; gap: 12px 16px; align-items: start; margin-top: 16px; padding-top: 16px; border-top: 1px solid #e1e7ef; }
.reauthorize-panel .el-button { grid-column: 1 / -1; justify-self: start; }
@media (max-width: 760px) {
  .subject-summary, .binding-grid, .binding-grid.is-primary { grid-template-columns: 1fr; }
  .subject-summary > div, .binding-grid > div { border-right: 0; border-bottom: 1px solid #d9e2ef; }
  .subject-summary > div:last-child, .binding-grid > div:last-child { border-bottom: 0; }
}
</style>
