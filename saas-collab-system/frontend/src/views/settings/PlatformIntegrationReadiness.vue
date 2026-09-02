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
        <div><strong>{{ gate.label }}</strong><small>{{ gate.ready ? '已通过' : gate.help }}</small></div>
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
                <router-link to="/integrations/configs">打开连接配置</router-link>
              </header>
              <el-table :data="row.configs || []" size="small" empty-text="尚未创建接入配置">
                <el-table-column label="配置名称" prop="account_alias" min-width="150" />
                <el-table-column label="环境" min-width="90"><template #default="scope">{{ environmentLabel(scope.row.environment) }}</template></el-table-column>
                <el-table-column label="合同版本" prop="contract_version" min-width="110" />
                <el-table-column label="回调地址" min-width="260"><template #default="scope"><span class="callback">{{ scope.row.callback_url || '未填写' }}</span></template></el-table-column>
                <el-table-column label="只读审批" min-width="110"><template #default="scope"><el-tag :type="scope.row.readonly_approved ? 'success' : 'info'">{{ scope.row.readonly_approved ? '已审批' : '未审批' }}</el-tag></template></el-table-column>
                <el-table-column label="待处理项" min-width="270"><template #default="scope">{{ scope.row.blocker_summary || '无' }}</template></el-table-column>
                <el-table-column label="操作" fixed="right" min-width="310">
                  <template #default="scope">
                    <el-button v-if="scope.row.can_repair_contract" link type="warning" :disabled="!canRepair" @click="repairContract(scope.row)">修复合同版本</el-button>
                    <el-button v-if="!scope.row.readonly_approved" link type="primary" :disabled="!canApprove || !scope.row.can_approve_readonly" @click="openApproval(scope.row, true)">审批生产只读</el-button>
                    <el-button v-else link type="danger" :disabled="!canApprove" @click="openApproval(scope.row, false)">撤销只读审批</el-button>
                    <el-button v-if="scope.row.callback_url" link @click="copyCallback(scope.row.callback_url)">复制回调地址</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="next-actions">
                <router-link to="/integrations/configs">维护凭据并执行检查</router-link>
                <router-link to="/master-data/stores">授权 Shopee 店铺</router-link>
                <router-link to="/integrations/sync-jobs">配置生产只读同步任务</router-link>
              </div>
            </section>
          </template>
        </el-table-column>
        <el-table-column label="平台" prop="platform" min-width="130" />
        <el-table-column label="当前接入状态" min-width="150"><template #default="{ row }"><el-tag :type="row.current_access_status === 'read_only_ready' ? 'success' : 'warning'">{{ row.current_access_status_label }}</el-tag></template></el-table-column>
        <el-table-column label="生产状态" min-width="160"><template #default="{ row }"><el-tag :type="row.production_status === 'production_readonly_ready' ? 'success' : 'danger'">{{ row.production_status_label }}</el-tag></template></el-table-column>
        <el-table-column label="配置概况" prop="config_summary" min-width="210" />
        <el-table-column label="待处理项" prop="blocker_summary" min-width="420" />
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
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  fetchPlatformIntegrationReadiness,
  repairPlatformIntegrationContract,
  setPlatformIntegrationReadonlyApproval
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const data = ref({ items: [], global_gates: {} });
const approvalVisible = ref(false);
const activeConfig = ref(null);
const approvalForm = reactive({ approved: true, reason: '', confirmed: false });

const rows = computed(() => data.value.items || []);
const canRepair = computed(() => auth.hasPermission('integrations.config.update'));
const canApprove = computed(() => auth.hasPermission('integrations.config.verify'));
const approvalReady = computed(() => approvalForm.confirmed && approvalForm.reason.trim().length >= 5);
const globalGates = computed(() => {
  const gates = data.value.global_gates || {};
  return [
    { key: 'security', label: '安全评审', ready: Boolean(gates.security_review_done), help: '请系统管理员完成生产平台安全审批' },
    { key: 'custody', label: '密钥托管', ready: Boolean(gates.credential_custody_done), help: '请系统管理员检查受控密钥托管服务' },
    { key: 'network', label: '网络隔离与白名单', ready: Boolean(gates.network_isolation_done), help: '请系统管理员配置只读网络模式和出站白名单' },
    { key: 'readonly', label: '只读同步开关', ready: Boolean(gates.readonly_sync_enabled), help: '请系统管理员启用生产只读同步运行开关' },
    { key: 'write', label: '生产写入保护', ready: data.value.production_write_enabled === false, help: '生产写入必须保持关闭' }
  ];
});

function environmentLabel(value) { return ({ mock: '模拟', sandbox: '沙箱', pilot: '试运行', production: '生产' })[value] || value || '—'; }
function responseError(response, fallback) { return response?.message || fallback; }

async function load() {
  loading.value = true;
  error.value = '';
  const response = await fetchPlatformIntegrationReadiness();
  if (response.success) data.value = response.data || { items: [], global_gates: {} };
  else error.value = responseError(response, '读取平台接入准备度失败。');
  loading.value = false;
}

async function repairContract(config) {
  if (!canRepair.value) return ElMessage.error('当前角色没有更新接入配置的权限。');
  saving.value = true;
  const preview = await repairPlatformIntegrationContract(config.id, { confirm: false, dry_run: true, expected_version: config.config_version });
  saving.value = false;
  if (!preview.success) return ElMessage.error(responseError(preview, '合同版本预检查失败。'));
  if (!preview.data?.changed) { ElMessage.success('合同版本已经是当前批准版本。'); return load(); }
  try {
    await ElMessageBox.confirm(`确认将“${config.account_alias}”的 Shopee 合同版本修复为 v2？该操作不会修改凭据、回调地址或生产写入状态。`, '修复合同版本', { type: 'warning', confirmButtonText: '确认修复' });
  } catch { return; }
  saving.value = true;
  const response = await repairPlatformIntegrationContract(config.id, { confirm: true, dry_run: false, expected_version: config.config_version });
  saving.value = false;
  if (!response.success) return ElMessage.error(responseError(response, '合同版本修复失败。'));
  ElMessage.success(response.message || '合同版本已修复。');
  await load();
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
.readiness-page { display: grid; gap: 16px; padding: 20px; }.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }.page-header h1 { margin: 0; color: #172033; font-size: 28px; }.page-header p, .table-card header p { margin: 7px 0 0; color: #607087; }.header-actions { display: flex; align-items: center; gap: 10px; }.gate-grid { display: grid; grid-template-columns: repeat(4, minmax(170px, 1fr)); gap: 12px; }.gate-grid article { display: flex; gap: 11px; min-height: 76px; padding: 15px; border: 1px solid #f0c9a0; border-radius: 8px; background: #fff8ed; }.gate-grid article > span { display: grid; place-items: center; flex: 0 0 28px; width: 28px; height: 28px; border-radius: 50%; color: #fff; background: #e6a23c; font-weight: 800; }.gate-grid article.ready { border-color: #b8e4d1; background: #f0fbf6; }.gate-grid article.ready > span { background: #22a06b; }.gate-grid strong, .gate-grid small { display: block; }.gate-grid small { margin-top: 6px; color: #6b778c; line-height: 1.45; }.table-card { overflow: hidden; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }.table-card > header, .config-panel > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 15px 16px; }.table-card h2 { margin: 0; font-size: 18px; }.table-card > header > strong { color: #607087; font-size: 12px; }.config-panel { margin: 4px 24px 16px; overflow: hidden; border: 1px solid #dce5ef; border-radius: 7px; background: #fff; }.config-panel > header { background: #f7f9fc; }.config-panel > header small { display: block; margin-top: 4px; color: #718096; }.config-panel a, .next-actions a { color: #1677d2; text-decoration: none; }.callback { display: block; overflow-wrap: anywhere; color: #4b5d73; font-size: 12px; }.next-actions { display: flex; gap: 20px; padding: 12px 16px; border-top: 1px solid #e5ebf2; background: #fafcff; }.approval-form { margin-top: 18px; }.approval-form :deep(.el-checkbox) { height: auto; white-space: normal; }.approval-form :deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; }
@media (max-width: 1000px) { .gate-grid { grid-template-columns: 1fr 1fr; }.page-header { flex-direction: column; } }
@media (max-width: 620px) { .gate-grid { grid-template-columns: 1fr; }.next-actions { align-items: flex-start; flex-direction: column; } }
</style>
