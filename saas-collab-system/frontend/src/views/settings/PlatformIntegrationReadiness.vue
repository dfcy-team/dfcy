<template>
  <section class="readiness-page">
    <header class="page-header">
      <div>
        <h1>平台接入准备度</h1>
        <p>按当前租户检查生产只读接入条件，并在同一页面完成配置整改、审批和后续授权。</p>
      </div>
      <div class="header-actions">
        <el-tag type="success" effect="plain">生产写入始终关闭</el-tag>
        <el-button :loading="loading" @click="load">重新检查</el-button>
      </div>
    </header>

    <el-alert
      title="页面只允许审批生产只读能力，不会开放订单、商品、库存或广告写入。全局安全门必须先由系统部署配置通过。"
      type="warning"
      :closable="false"
      show-icon
    />

    <section class="gate-grid" aria-label="全局安全门">
      <article v-for="gate in globalGates" :key="gate.key" :class="{ ready: gate.ready }">
        <span>{{ gate.ready ? '✓' : '!' }}</span>
        <div class="gate-content">
          <strong>{{ gate.label }}</strong>
          <small>{{ gate.ready ? '已通过' : gate.help }}</small>
          <el-button
            link
            size="small"
            :disabled="!gate.access.allowed"
            :title="gate.access.allowed ? gate.actionHint : gate.access.reason"
            @click="openGateSettings(gate)"
          >{{ gate.ready ? '查看配置' : '去配置' }}</el-button>
        </div>
      </article>
    </section>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <section class="table-card">
      <header>
        <div><h2>平台生产只读状态</h2><p>展开平台后可查看并处理当前租户的具体配置。</p></div>
        <strong>{{ rows.length }} 个平台</strong>
      </header>
      <el-table v-loading="loading" :data="rows" row-key="platform_code" empty-text="暂无平台准备度数据">
        <el-table-column type="expand">
          <template #default="{ row }">
            <section class="config-panel">
              <header>
                <div><strong>{{ row.platform }} 配置</strong><small>{{ row.config_summary }}</small></div>
                <el-button
                  link
                  :disabled="!configViewAccess.allowed"
                  :title="configViewAccess.allowed ? '查看并处理该平台接入配置' : configViewAccess.reason"
                  @click="openConfigWorkspace(row)"
                >打开连接配置</el-button>
              </header>
              <el-table :data="row.configs || []" size="small" empty-text="尚未创建接入配置">
                <el-table-column label="配置名称" prop="account_alias" min-width="150" />
                <el-table-column label="环境" min-width="90"><template #default="scope">{{ environmentLabel(scope.row.environment) }}</template></el-table-column>
                <el-table-column label="合同版本" prop="contract_version" min-width="110" />
                <el-table-column label="回调地址" min-width="260"><template #default="scope"><span class="callback">{{ scope.row.callback_url || '未填写' }}</span></template></el-table-column>
                <el-table-column label="只读审批" min-width="110"><template #default="scope"><el-tag :type="scope.row.readonly_approved ? 'success' : 'info'">{{ scope.row.readonly_approved ? '已审批' : '未审批' }}</el-tag></template></el-table-column>
                <el-table-column label="待处理项" min-width="360">
                  <template #default="scope">
                    <ul v-if="blockerItems(scope.row).length" class="blocker-list" :aria-label="`待处理项：${scope.row.blocker_summary || '无'}`">
                      <li v-for="item in blockerItems(scope.row)" :key="item.code">
                        <span>{{ item.label }}</span>
                        <el-button link size="small" :disabled="!item.access.allowed" :title="item.access.allowed ? item.actionHint : item.access.reason" @click="openBlockerAction(scope.row, item)">{{ item.actionLabel }}</el-button>
                      </li>
                    </ul>
                    <span v-else>无</span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" fixed="right" min-width="310">
                  <template #default="scope">
                    <el-button v-if="scope.row.can_repair_contract" link type="warning" :loading="repairingId === scope.row.id" :disabled="!canRepair || saving" @click="repairContract(scope.row)">修复合同版本</el-button>
                    <el-button v-if="!scope.row.readonly_approved" link type="primary" :disabled="!canApprove || !scope.row.can_approve_readonly" @click="openApproval(scope.row, true)">审批生产只读</el-button>
                    <el-button v-else link type="danger" :disabled="!canApprove" @click="openApproval(scope.row, false)">撤销只读审批</el-button>
                    <el-button v-if="scope.row.callback_url" link @click="copyCallback(scope.row.callback_url)">复制回调地址</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="next-actions">
                <el-button link :disabled="!configViewAccess.allowed" :title="configViewAccess.allowed ? '维护凭据并执行检查' : configViewAccess.reason" @click="openConfigWorkspace(row, 'credentials')">维护凭据并执行检查</el-button>
                <el-button link :disabled="!storeViewAccess.allowed" :title="storeViewAccess.allowed ? '进入该平台店铺授权' : storeViewAccess.reason" @click="openAuthorization(row)">授权 {{ row.platform || row.platform_code }} 店铺</el-button>
                <el-button link :disabled="!syncViewAccess.allowed" :title="syncViewAccess.allowed ? '配置生产只读同步任务' : syncViewAccess.reason" @click="openSyncJobs(row)">配置生产只读同步任务</el-button>
              </div>
            </section>
          </template>
        </el-table-column>
        <el-table-column label="平台" prop="platform" min-width="130" />
        <el-table-column label="当前接入状态" min-width="150"><template #default="{ row }"><el-tag :type="row.current_access_status === 'read_only_ready' ? 'success' : 'warning'">{{ row.current_access_status_label }}</el-tag></template></el-table-column>
        <el-table-column label="生产状态" min-width="160"><template #default="{ row }"><el-tag :type="row.production_status === 'production_readonly_ready' ? 'success' : 'danger'">{{ row.production_status_label }}</el-tag></template></el-table-column>
        <el-table-column label="配置概况" prop="config_summary" min-width="210" />
        <el-table-column label="待处理项" min-width="470">
          <template #default="{ row }">
            <ul v-if="blockerItems(row).length" class="blocker-list platform-blockers" :aria-label="`待处理项：${row.blocker_summary || '无'}`">
              <li v-for="item in blockerItems(row)" :key="item.code">
                <span>{{ item.label }}</span>
                <el-button link size="small" :disabled="!item.access.allowed" :title="item.access.allowed ? item.actionHint : item.access.reason" @click="openBlockerAction(row, item)">{{ item.actionLabel }}</el-button>
              </li>
            </ul>
            <span v-else>无</span>
          </template>
        </el-table-column>
        <el-table-column label="操作提示" min-width="150"><template #default="{ row }">{{ row.production_status === 'production_readonly_ready' ? '可进入店铺授权/只读任务' : '展开后逐项处理' }}</template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="approvalVisible" :title="approvalForm.approved ? '审批生产只读' : '撤销生产只读审批'" width="520px" destroy-on-close>
      <el-alert
        :title="approvalForm.approved ? '审批后仅允许已配置的只读 API；生产写入仍保持关闭。' : '撤销后该配置将不能发起新的生产只读授权和同步。'"
        :type="approvalForm.approved ? 'warning' : 'info'"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="approval-form">
        <el-form-item label="配置"><el-input :model-value="activeConfig?.account_alias || ''" disabled /></el-form-item>
        <el-form-item label="审批/撤销原因"><el-input v-model="approvalForm.reason" type="textarea" :rows="3" maxlength="240" show-word-limit /></el-form-item>
        <el-checkbox v-model="approvalForm.confirmed">我已核对安全门、凭据、合同版本和回调地址，确认仅启用生产只读。</el-checkbox>
      </el-form>
      <template #footer><el-button @click="approvalVisible = false">取消</el-button><el-button :type="approvalForm.approved ? 'primary' : 'danger'" :loading="saving" :disabled="!approvalReady" @click="submitApproval">确认</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  fetchPlatformIntegrationReadiness,
  repairPlatformIntegrationContract,
  setPlatformIntegrationReadonlyApproval
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const router = useRouter();
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const data = ref({ items: [], global_gates: {} });
const approvalVisible = ref(false);
const activeConfig = ref(null);
const repairingId = ref(null);
const approvalForm = reactive({ approved: true, reason: '', confirmed: false });

const rows = computed(() => data.value.items || []);
const canRepair = computed(() => auth.hasPermission('integrations.config.update'));
const canApprove = computed(() => auth.hasPermission('integrations.config.verify'));
const configViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.config.view', unauthorizedBehavior: 'disable' }));
const storeViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.store.view', unauthorizedBehavior: 'disable' }));
const syncViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.view', unauthorizedBehavior: 'disable' }));
const systemConfigAccess = computed(() => {
  const missing = ['config.system.manage', 'config.view'].filter((code) => !auth.hasPermission(code));
  return { allowed: missing.length === 0, disabled: missing.length > 0, visible: true, reason: missing.length ? `缺少操作权限：${missing.join('、')}` : '' };
});
const approvalReady = computed(() => approvalForm.confirmed && approvalForm.reason.trim().length >= 5);
const globalGates = computed(() => {
  const gates = data.value.global_gates || {};
  const gateAccess = systemConfigAccess.value;
  return [
    { key: 'security', label: '安全评审', ready: Boolean(gates.security_review_done), help: '请系统管理员完成生产平台安全审批', access: gateAccess, actionHint: '打开生产环境配置，维护安全审批状态' },
    { key: 'custody', label: '密钥托管', ready: Boolean(gates.credential_custody_done), help: '请系统管理员检查受控密钥托管服务', access: gateAccess, actionHint: '打开生产环境配置，维护密钥托管引用' },
    { key: 'network', label: '网络隔离与白名单', ready: Boolean(gates.network_isolation_done), help: '请系统管理员配置只读网络模式和出站白名单', access: gateAccess, actionHint: '打开生产环境配置，维护网络模式和域名白名单' },
    { key: 'readonly', label: '只读同步开关', ready: Boolean(gates.readonly_sync_enabled), help: '请系统管理员启用生产只读同步运行开关', access: gateAccess, actionHint: '打开生产环境配置，维护只读同步开关' },
    { key: 'write', label: '生产写入保护', ready: data.value.production_write_enabled === false, help: '生产写入必须保持关闭', access: gateAccess, actionHint: '打开生产环境配置查看写入保护状态' }
  ];
});

const BLOCKER_LABELS = {
  config_missing: '尚未创建接入配置', platform_mismatch: '配置平台不匹配', environment_not_live: '配置不是试运行或生产环境',
  platform_network_mode_disabled: '生产平台只读网络模式未启用', platform_security_not_approved: '生产平台安全审批未通过',
  credential_custody_not_approved: '密钥托管服务未通过检查', outbound_host_allowlist_missing: '平台出站域名白名单未配置',
  platform_contract_not_enabled: '平台合同开关未启用', readonly_sync_feature_disabled: '生产只读同步功能未启用',
  network_not_approved: '当前配置的网络访问未批准', write_sync_enabled: '当前配置异常启用了写同步',
  config_not_approved: '接入配置尚未审核通过', credential_not_configured: '开发者凭据尚未配置',
  credential_reference_missing: '开发者凭据引用缺失', contract_not_approved: '接口合同版本不符合当前平台要求',
  callback_missing: '授权回调地址未填写', callback_allowlist_missing: '授权回调白名单未配置',
  callback_mismatch: '授权回调地址与服务器配置不一致', callback_not_allowlisted: '授权回调地址不在白名单内',
  public_app_id_missing: '平台应用 ID 未填写', readonly_not_approved: '生产只读能力尚未审批'
};

const BLOCKER_ACTIONS = {
  config_missing: { actionLabel: '新建接入配置', route: '/integrations/configs', action: 'create', permission: 'integrations.config.view', actionHint: '进入连接配置并创建平台配置' },
  platform_mismatch: { actionLabel: '检查配置', route: '/integrations/configs', action: 'verify', permission: 'integrations.config.view', actionHint: '进入连接配置检查平台配置' },
  environment_not_live: { actionLabel: '调整配置', route: '/integrations/configs', action: 'verify', permission: 'integrations.config.view', actionHint: '进入连接配置检查环境' },
  platform_network_mode_disabled: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '配置生产只读网络模式' },
  platform_security_not_approved: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '完成生产平台安全审批' },
  credential_custody_not_approved: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '配置密钥托管服务' },
  outbound_host_allowlist_missing: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '配置平台出站域名白名单' },
  platform_contract_not_enabled: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '配置平台合同开关' },
  readonly_sync_feature_disabled: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '启用生产只读同步开关' },
  network_not_approved: { actionLabel: '检查配置', route: '/integrations/configs', action: 'verify', permission: 'integrations.config.view', actionHint: '检查租户接入配置网络审批状态' },
  write_sync_enabled: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '确认生产写入保护保持关闭' },
  config_not_approved: { actionLabel: '检查配置', route: '/integrations/configs', action: 'verify', permission: 'integrations.config.view', actionHint: '检查接入配置并执行验证' },
  credential_not_configured: { actionLabel: '维护凭据', route: '/integrations/configs', action: 'credentials', permission: 'integrations.config.view', actionHint: '进入连接配置维护开发者凭据' },
  credential_reference_missing: { actionLabel: '维护凭据', route: '/integrations/configs', action: 'credentials', permission: 'integrations.config.view', actionHint: '进入连接配置维护凭据引用' },
  contract_not_approved: { actionLabel: '检查合同', route: '/integrations/configs', action: 'verify', permission: 'integrations.config.view', actionHint: '进入连接配置检查合同版本' },
  callback_missing: { actionLabel: '维护回调', route: '/integrations/configs', action: 'credentials', permission: 'integrations.config.view', actionHint: '进入连接配置维护 OAuth 回调地址' },
  callback_allowlist_missing: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '配置 OAuth 回调白名单' },
  callback_mismatch: { actionLabel: '维护回调', route: '/integrations/configs', action: 'credentials', permission: 'integrations.config.view', actionHint: '校正 OAuth 回调地址' },
  callback_not_allowlisted: { actionLabel: '去配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '将回调地址加入白名单' },
  public_app_id_missing: { actionLabel: '维护凭据', route: '/integrations/configs', action: 'credentials', permission: 'integrations.config.view', actionHint: '进入连接配置填写公开应用 ID' },
  readonly_not_approved: { actionLabel: '审批只读', action: 'approve_readonly', permission: 'integrations.config.verify', actionHint: '在生产准入页审批生产只读能力' }
};

function permissionAccess(permission) {
  const permissions = Array.isArray(permission) ? permission : [permission];
  const missing = permissions.filter((code) => !auth.hasPermission(code));
  return {
    allowed: missing.length === 0,
    visible: true,
    disabled: missing.length > 0,
    reason: missing.length ? `缺少操作权限：${missing.join('、')}` : ''
  };
}

function configForRow(row) {
  const configs = Array.isArray(row?.configs) ? row.configs : [];
  return configs.find((item) => item.id) || configs[0] || row;
}

function blockerItems(row) {
  const source = row?.blocker_codes || row?.blockers || [];
  const codes = Array.isArray(source) ? source : String(source || '').split(/[;,]/).map((item) => item.trim()).filter(Boolean);
  return codes.map((entry) => {
    const code = typeof entry === 'object' ? (entry.code || entry.key || '') : entry;
    const action = BLOCKER_ACTIONS[code] || { actionLabel: '查看配置', route: '/integrations/production-settings', permission: ['config.system.manage', 'config.view'], actionHint: '查看生产环境配置' };
    return { code, label: typeof entry === 'object' ? (entry.label || BLOCKER_LABELS[code] || code) : (BLOCKER_LABELS[code] || code), ...action, access: permissionAccess(action.permission) };
  });
}

function openGateSettings(gate) {
  if (!gate.access.allowed) return ElMessage.warning(gate.access.reason);
  router.push({ path: '/integrations/production-settings', query: { focus: gate.key } });
}

function openConfigWorkspace(row, action = '') {
  if (!configViewAccess.value.allowed) return ElMessage.warning(configViewAccess.value.reason);
  const config = configForRow(row);
  const query = { platform: row.platform_code, ...(config?.id ? { config_id: config.id } : {}), ...(action ? { action } : {}) };
  router.push({ path: '/integrations/configs', query });
}

function openAuthorization(row) {
  if (!storeViewAccess.value.allowed) return ElMessage.warning(storeViewAccess.value.reason);
  router.push({ path: '/integrations/authorizations', query: { platform: row.platform_code } });
}

function openSyncJobs(row) {
  if (!syncViewAccess.value.allowed) return ElMessage.warning(syncViewAccess.value.reason);
  router.push({ path: '/integrations/sync-jobs', query: { platform: row.platform_code } });
}

function openBlockerAction(row, item) {
  if (!item.access.allowed) return ElMessage.warning(item.access.reason);
  if (item.action === 'approve_readonly') {
    const config = configForRow(row);
    if (config?.id) return openApproval(config, true);
  }
  if (!item.route) return;
  const config = configForRow(row);
  router.push({ path: item.route, query: { ...(row.platform_code ? { platform: row.platform_code } : {}), ...(config?.id ? { config_id: config.id } : {}), ...(item.action ? { action: item.action } : {}) } });
}

function environmentLabel(value) { return ({ mock: '模拟', sandbox: '沙箱', pilot: '试运行', production: '生产' })[value] || value || '—'; }
function responseError(response, fallback) { return response?.message || fallback; }

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const response = await fetchPlatformIntegrationReadiness();
    if (response.success) data.value = response.data || { items: [], global_gates: {} };
    else error.value = responseError(response, '读取平台接入准备度失败。');
  } catch (err) {
    error.value = responseError(err, '读取平台接入准备度失败。');
  } finally {
    loading.value = false;
  }
}

async function repairContract(config) {
  if (!canRepair.value) return ElMessage.error('当前角色没有更新接入配置的权限。');
  if (repairingId.value) return;
  repairingId.value = config.id;
  saving.value = true;
  try {
    const preview = await repairPlatformIntegrationContract(config.id, { confirm: false, dry_run: true, expected_version: config.config_version });
    if (!preview.success) return ElMessage.error(responseError(preview, '合同版本预检查失败。'));
    if (!preview.data?.changed) { ElMessage.success('合同版本已经是当前批准版本。'); return load(); }
    const targetContractVersion = preview.data?.target_contract_version;
    const targetContractLabel = targetContractVersion ? `批准版本 ${targetContractVersion}` : '当前批准版本';
    try {
      await ElMessageBox.confirm(`确认将“${config.account_alias}”的合同版本修复为${targetContractLabel}？该操作不会修改凭据、回调地址或生产写入状态。`, '修复合同版本', { type: 'warning', confirmButtonText: '确认修复' });
    } catch { return; }
    const response = await repairPlatformIntegrationContract(config.id, { confirm: true, dry_run: false, expected_version: config.config_version });
    if (!response.success) return ElMessage.error(responseError(response, '合同版本修复失败。'));
    ElMessage.success(response.message || '合同版本已修复。');
    await load();
  } catch (repairError) {
    ElMessage.error(responseError(repairError, '合同版本修复失败。'));
  } finally {
    saving.value = false;
    repairingId.value = null;
  }
}

function openApproval(config, approved) {
  activeConfig.value = config;
  Object.assign(approvalForm, { approved, reason: approved ? '已核对生产只读接入条件并申请启用' : '撤销当前生产只读审批', confirmed: false });
  approvalVisible.value = true;
}

async function submitApproval() {
  if (!activeConfig.value || !approvalReady.value) return;
  saving.value = true;
  const response = await setPlatformIntegrationReadonlyApproval(activeConfig.value.id, {
    approved: approvalForm.approved,
    confirm: true,
    expected_version: activeConfig.value.config_version,
    reason: approvalForm.reason.trim()
  });
  saving.value = false;
  if (!response.success) return ElMessage.error(responseError(response, '生产只读审批操作失败。'));
  approvalVisible.value = false;
  ElMessage.success(response.message || (approvalForm.approved ? '生产只读审批已完成。' : '生产只读审批已撤销。'));
  await load();
}

async function copyCallback(value) {
  try { await navigator.clipboard.writeText(value); ElMessage.success('回调地址已复制。'); }
  catch { ElMessage.warning('浏览器未允许复制，请手动复制回调地址。'); }
}

onMounted(load);
</script>

<style scoped>
.readiness-page { display: grid; gap: 16px; padding: 20px; }.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }.page-header h1 { margin: 0; color: #172033; font-size: 28px; }.page-header p, .table-card header p { margin: 7px 0 0; color: #607087; }.header-actions { display: flex; align-items: center; gap: 10px; }.gate-grid { display: grid; grid-template-columns: repeat(4, minmax(170px, 1fr)); gap: 12px; }.gate-grid article { display: flex; gap: 11px; min-height: 76px; padding: 15px; border: 1px solid #f0c9a0; border-radius: 8px; background: #fff8ed; }.gate-grid article > span { display: grid; place-items: center; flex: 0 0 28px; width: 28px; height: 28px; border-radius: 50%; color: #fff; background: #e6a23c; font-weight: 800; }.gate-grid article.ready { border-color: #b8e4d1; background: #f0fbf6; }.gate-grid article.ready > span { background: #22a06b; }.gate-content { min-width: 0; }.gate-grid strong, .gate-grid small { display: block; }.gate-grid small { margin-top: 6px; color: #6b778c; line-height: 1.45; }.gate-grid .el-button { margin-top: 5px; padding: 0; }.table-card { overflow: hidden; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }.table-card > header, .config-panel > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 15px 16px; }.table-card h2 { margin: 0; font-size: 18px; }.table-card > header > strong { color: #607087; font-size: 12px; }.config-panel { margin: 4px 24px 16px; overflow: hidden; border: 1px solid #dce5ef; border-radius: 7px; background: #fff; }.config-panel > header { background: #f7f9fc; }.config-panel > header small { display: block; margin-top: 4px; color: #718096; }.config-panel a, .next-actions a { color: #1677d2; text-decoration: none; }.callback { display: block; overflow-wrap: anywhere; color: #4b5d73; font-size: 12px; }.next-actions { display: flex; gap: 20px; padding: 12px 16px; border-top: 1px solid #e5ebf2; background: #fafcff; }.blocker-list { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }.blocker-list li { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; line-height: 1.4; }.blocker-list li > span { overflow-wrap: anywhere; }.blocker-list .el-button { flex: 0 0 auto; padding: 0; }.platform-blockers { max-width: 440px; }.approval-form { margin-top: 18px; }.approval-form :deep(.el-checkbox) { height: auto; white-space: normal; }.approval-form :deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; }
@media (max-width: 1000px) { .gate-grid { grid-template-columns: 1fr 1fr; }.page-header { flex-direction: column; } }
@media (max-width: 620px) { .gate-grid { grid-template-columns: 1fr; }.next-actions { align-items: flex-start; flex-direction: column; } }
</style>
