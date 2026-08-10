<template>
  <main v-loading="loading" class="editor-page">
    <header class="editor-heading">
      <div>
        <el-button text @click="router.push('/integrations/configs')">← 返回连接配置</el-button>
        <div class="title-row">
          <h1>{{ isNew ? '新建平台连接' : form.account_alias || '连接配置' }}</h1>
          <el-tag :type="form.status === 'verified' ? 'success' : 'warning'">{{ form.status }}</el-tag>
        </div>
        <p>平台参数与凭据分开保存。凭据写入后只保留托管引用和固定掩码。</p>
      </div>
      <div class="heading-actions">
        <el-button v-if="!isNew && canVerify" @click="verify">验证连接</el-button>
        <el-button v-if="!isNew && canDisable" type="danger" plain @click="disable">禁用</el-button>
        <el-button v-if="canSave" type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
      </div>
    </header>

    <el-alert
      title="Production 同步保持关闭。当前页面仅配置 OAuth、authorized shop 与最小只读验证所需参数。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="editor-card">
      <div class="section-heading"><div><h2>基础配置</h2><p>选择平台和环境后，字段由后端 Schema 动态返回。</p></div></div>
      <el-form label-position="top" class="form-grid">
        <el-form-item label="平台" required>
          <el-select v-model="form.platform" :disabled="!isNew" @change="changePlatform">
            <el-option label="Shopee" value="shopee" />
            <el-option label="TikTok Shop" value="tiktok" />
          </el-select>
        </el-form-item>
        <el-form-item label="应用别名" required><el-input v-model="form.account_alias" maxlength="120" /></el-form-item>
        <el-form-item label="环境" required>
          <el-select v-model="form.environment" :disabled="!isNew" @change="loadSchema">
            <el-option v-for="item in schema.environments || []" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="合同版本">
          <el-select v-model="form.contract_version" clearable placeholder="选择已审核合同版本">
            <el-option v-for="version in schema.contract_versions || []" :key="version" :label="version" :value="version" />
          </el-select>
        </el-form-item>
        <el-form-item class="span-2" label="地区 / 市场" required>
          <el-checkbox-group v-model="form.regions">
            <el-checkbox v-for="item in schema.regions || []" :key="item.value" :value="item.value">{{ item.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item class="span-2" label="Callback URL" required>
          <el-input
            v-model="form.callback_url"
            placeholder="Pilot 可填 http://127.0.0.1:8000/...；正式环境必须使用 HTTPS"
          />
        </el-form-item>
        <el-form-item
          v-for="field in schema.public_fields || []"
          :key="field.key"
          :label="field.label"
          :required="field.required"
        >
          <el-input v-model="form.platform_config[field.key]" />
        </el-form-item>
        <el-form-item v-if="(schema.scope_options || []).length" class="span-2" label="最小只读 Scope">
          <el-checkbox-group v-model="form.scopes">
            <el-checkbox v-for="item in schema.scope_options" :key="item.value" :value="item.value">{{ item.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
    </section>

    <section class="editor-card">
      <div class="section-heading"><div><h2>网络边界</h2><p>超时有硬上限；真实网络还需要服务端环境审批和域名白名单。</p></div></div>
      <el-form label-position="top" class="form-grid">
        <el-form-item label="连接超时（秒）"><el-input-number v-model="form.connect_timeout_seconds" :min="1" :max="10" /></el-form-item>
        <el-form-item label="读取超时（秒）"><el-input-number v-model="form.read_timeout_seconds" :min="1" :max="30" /></el-form-item>
        <el-form-item label="代理配置名"><el-input v-model="form.proxy_profile" placeholder="可选；不填写则使用批准的默认出口" /></el-form-item>
        <el-form-item label="真实平台网络">
          <el-switch v-model="form.network_enabled" active-text="请求启用" inactive-text="关闭" />
        </el-form-item>
        <el-form-item label="读取同步"><el-switch :model-value="false" disabled inactive-text="本阶段强制关闭" /></el-form-item>
        <el-form-item label="写入同步"><el-switch :model-value="false" disabled inactive-text="本任务禁止" /></el-form-item>
      </el-form>
    </section>

    <section v-if="!isNew" class="editor-card credential-card">
      <div class="section-heading">
        <div><h2>凭据托管</h2><p>空白表示保持不变。替换值只在本次请求内存中使用，响应与审计不会返回原文。</p></div>
        <el-tag :type="credentialConfigured ? 'success' : 'info'">{{ credentialConfigured ? '******** 已配置' : '未配置' }}</el-tag>
      </div>
      <SecretField
        v-for="field in visibleSecretFields"
        :key="field.key"
        v-model="secretValues[field.key]"
        :label="field.label"
        :configured="credentialConfigured"
      />
      <el-switch
        v-if="(schema.secret_fields || []).some((field) => field.advanced)"
        v-model="advancedCredentialMode"
        class="advanced-switch"
        active-text="高级凭据替换（迁移/故障恢复）"
        inactive-text="仅配置应用密钥"
      />
      <div class="credential-actions">
        <el-input v-model="credentialReason" maxlength="240" placeholder="填写替换原因（至少 5 个字符）" />
        <el-button v-if="canRotate" type="primary" :disabled="!hasSecretChanges" :loading="rotating" @click="rotateCredentials">保存并托管新凭据</el-button>
        <el-button v-if="canClear && credentialConfigured" type="danger" plain @click="clearCredentials">清除凭据</el-button>
      </div>
    </section>

    <section v-if="!isNew" class="editor-card">
      <div class="section-heading"><div><h2>店铺授权</h2><p>配置保存并通过托管后，才可前往平台官方页面授权测试店铺。</p></div></div>
      <MarketplaceAuthorizationPanel />
    </section>

    <section v-if="!isNew && canAudit" class="editor-card">
      <div class="section-heading"><div><h2>脱敏审计</h2><p>仅记录操作者、动作、结果、掩码、引用版本和受控错误码。</p></div><el-button text @click="loadAudit">刷新</el-button></div>
      <el-table :data="auditRows" empty-text="暂无审计记录">
        <el-table-column prop="created_at" label="时间" min-width="180" />
        <el-table-column prop="action" label="动作" min-width="150" />
        <el-table-column prop="actor_id" label="操作者" width="100" />
        <el-table-column prop="result" label="结果" width="110" />
        <el-table-column label="详情（已脱敏）" min-width="260"><template #default="{ row }">{{ safeDetail(row.masked_detail) }}</template></el-table-column>
      </el-table>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import MarketplaceAuthorizationPanel from '../../components/MarketplaceAuthorizationPanel.vue';
import SecretField from '../../components/integrations/SecretField.vue';
import {
  clearIntegrationCredentials,
  createIntegrationConfig,
  disableIntegrationConfig,
  fetchIntegrationAudit,
  fetchIntegrationConfigDetail,
  fetchIntegrationConfigSchema,
  rotateIntegrationCredentials,
  updateIntegrationConfig,
  verifyIntegrationConfig
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const isNew = computed(() => route.params.id === undefined || route.params.id === 'new');
const loading = ref(false);
const saving = ref(false);
const rotating = ref(false);
const schema = ref({ environments: [], regions: [], scope_options: [], public_fields: [], secret_fields: [] });
const auditRows = ref([]);
const secretValues = reactive({});
const credentialReason = ref('');
const advancedCredentialMode = ref(false);
const form = reactive({
  platform: 'shopee', account_alias: '', environment: 'sandbox', status: 'draft', regions: ['PH'],
  contract_version: '', callback_url: 'https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/shopee/',
  scopes: [], platform_config: {}, connect_timeout_seconds: 3, read_timeout_seconds: 8, proxy_profile: '',
  network_enabled: false, sync_read_enabled: false, sync_write_enabled: false, config_version: 1,
  credential_status: 'unconfigured', credential_mask: {}
});

const canSave = computed(() => auth.hasPermission(isNew.value ? 'integrations.config.create' : 'integrations.config.update'));
const canVerify = computed(() => auth.hasPermission('integrations.config.verify'));
const canDisable = computed(() => auth.hasPermission('integrations.config.disable'));
const canRotate = computed(() => auth.hasPermission('integrations.credential.rotate'));
const canClear = computed(() => auth.hasPermission('integrations.credential.clear'));
const canAudit = computed(() => auth.hasPermission('integrations.audit.view'));
const credentialConfigured = computed(() => form.credential_status === 'configured' && Object.keys(form.credential_mask || {}).length > 0);
const hasSecretChanges = computed(() => Object.values(secretValues).some((value) => Boolean(value)) && credentialReason.value.trim().length >= 5);
const visibleSecretFields = computed(() => (schema.value.secret_fields || []).filter((field) => !field.advanced || advancedCredentialMode.value));

function dataOf(response) { return response?.success ? response.data : null; }
function safeDetail(detail) {
  const text = JSON.stringify(detail || {});
  return text.length > 180 ? `${text.slice(0, 180)}…` : text;
}
function applyConfig(data) {
  for (const key of Object.keys(form)) if (key in data) form[key] = data[key];
  form.platform_config = { ...(data.platform_config || {}) };
  form.regions = [...(data.regions || [])];
  form.scopes = [...(data.scopes || [])];
}
async function loadSchema() {
  const response = await fetchIntegrationConfigSchema(form.platform, form.environment);
  if (response.success) {
    schema.value = response.data;
    for (const field of schema.value.public_fields || []) if (!(field.key in form.platform_config)) form.platform_config[field.key] = '';
    if (isNew.value) {
      const path = form.platform === 'tiktok' ? 'tiktok' : 'shopee';
      form.callback_url = `https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/${path}/`;
      form.scopes = (schema.value.scope_options || []).map((item) => item.value);
      form.contract_version = (schema.value.contract_versions || [])[0] || '';
    }
  }
}
async function changePlatform() {
  form.platform_config = {};
  await loadSchema();
}
async function loadAudit() {
  if (isNew.value || !canAudit.value) return;
  const response = await fetchIntegrationAudit(route.params.id);
  auditRows.value = Array.isArray(response?.data) ? response.data : [];
}
async function initialize() {
  loading.value = true;
  if (!isNew.value) {
    const response = await fetchIntegrationConfigDetail(route.params.id);
    if (response.success) applyConfig(response.data);
  }
  await loadSchema();
  await loadAudit();
  loading.value = false;
}
function configPayload() {
  return {
    platform: form.platform,
    account_alias: form.account_alias.trim(),
    environment: form.environment,
    status: form.status,
    regions: form.regions,
    contract_version: form.contract_version,
    callback_url: form.callback_url,
    scopes: form.scopes,
    platform_config: form.platform_config,
    connect_timeout_seconds: form.connect_timeout_seconds,
    read_timeout_seconds: form.read_timeout_seconds,
    proxy_profile: form.proxy_profile,
    network_enabled: form.network_enabled,
    sync_read_enabled: false,
    sync_write_enabled: false
  };
}
async function saveConfig() {
  try {
    await ElMessageBox.confirm(
      `确认保存：${form.platform} / ${form.environment} / ${(form.regions || []).join(', ')}。凭据不会随普通配置提交，生产同步保持关闭。`,
      '配置变更摘要',
      { confirmButtonText: '确认保存', cancelButtonText: '返回检查' }
    );
  } catch { return; }
  saving.value = true;
  const response = isNew.value
    ? await createIntegrationConfig(configPayload())
    : await updateIntegrationConfig(route.params.id, { ...configPayload(), version: form.config_version });
  saving.value = false;
  if (!response.success) return ElMessage.error(response.message || '配置保存失败');
  applyConfig(response.data);
  ElMessage.success('配置已保存');
  if (isNew.value) await router.replace(`/integrations/configs/${response.data.id}`);
}
async function rotateCredentials() {
  const credentials = Object.fromEntries(Object.entries(secretValues).filter(([, value]) => value));
  rotating.value = true;
  const response = await rotateIntegrationCredentials(route.params.id, {
    version: form.config_version,
    reason: credentialReason.value.trim(),
    credentials,
    verify_after_save: false
  });
  for (const key of Object.keys(secretValues)) secretValues[key] = '';
  credentialReason.value = '';
  rotating.value = false;
  if (!response.success) return ElMessage.error(response.message || '凭据托管失败');
  applyConfig(response.data);
  ElMessage.success('新凭据已写入托管服务；页面未保留原文');
  await loadAudit();
}
async function clearCredentials() {
  let value;
  try {
    ({ value } = await ElMessageBox.prompt('此操作会撤销托管引用，且不能通过普通编辑恢复。请输入清除原因。', '确认清除凭据', {
      confirmButtonText: '确认清除', cancelButtonText: '取消', inputPattern: /.{5,}/, inputErrorMessage: '原因至少 5 个字符', type: 'warning'
    }));
  } catch { return; }
  const response = await clearIntegrationCredentials(route.params.id, { version: form.config_version, reason: value });
  if (!response.success) return ElMessage.error(response.message || '凭据清除失败');
  applyConfig(response.data);
  ElMessage.success('托管引用已撤销并清除');
  await loadAudit();
}
async function verify() {
  const response = await verifyIntegrationConfig(route.params.id);
  response.success ? ElMessage.success('验证请求已完成') : ElMessage.error(response.message || '验证失败');
}
async function disable() {
  try {
    await ElMessageBox.confirm('确认禁用当前连接配置？真实网络和后续授权操作将保持关闭。', '禁用连接', { type: 'warning' });
  } catch { return; }
  const response = await disableIntegrationConfig(route.params.id);
  if (response.success) { applyConfig(response.data); ElMessage.success('连接配置已禁用'); }
}
onMounted(initialize);
</script>

<style scoped>
.editor-page { display: grid; gap: 20px; max-width: 1180px; margin: 0 auto; }
.editor-heading { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; }
.editor-heading p { margin: 8px 0 0; color: var(--el-text-color-secondary); }
.title-row { display: flex; align-items: center; gap: 12px; }
.title-row h1 { margin: 8px 0 0; font-size: 28px; letter-spacing: -.02em; }
.heading-actions { display: flex; gap: 10px; }
.editor-card { padding: 22px; border: 1px solid var(--el-border-color-light); border-radius: 10px; background: var(--el-bg-color); box-shadow: 0 1px 2px rgb(15 23 42 / 4%); }
.section-heading { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 20px; }
.section-heading h2 { margin: 0; font-size: 18px; }
.section-heading p { margin: 6px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 24px; }
.span-2 { grid-column: 1 / -1; }
.credential-actions { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; margin-top: 20px; }
.advanced-switch { margin-top: 16px; }
.credential-card :deep(.el-alert) { margin-bottom: 16px; }
@media (max-width: 760px) { .editor-heading { align-items: flex-start; flex-direction: column; } .heading-actions { flex-wrap: wrap; } .form-grid { grid-template-columns: 1fr; } .span-2 { grid-column: auto; } .credential-actions { grid-template-columns: 1fr; } }
</style>
